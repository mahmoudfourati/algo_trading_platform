"""Layer 2 anomaly service.

Consumes ValidatedTick, emits anomaly/system state, and publishes ScoredTick.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from kafka import KafkaConsumer
from prometheus_client import Counter, Gauge, Histogram

from services.layer1_validated.kafka_json_publisher import KafkaJsonPublisher, KafkaJsonPublisherConfig
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.service_health import mark_service_healthy
from shared.schemas import ScoredTick, ValidatedTick

from .engine import DecisionGate, Layer2ScoringEngine

logger = logging.getLogger(__name__)


_raw_in_total = Counter("layer2_raw_in_total", "ValidatedTick messages consumed (including bad).")
_bad_in_total = Counter("layer2_bad_in_total", "ValidatedTick messages that failed decoding/validation.")
_scored_out_total = Counter("layer2_scored_out_total", "ScoredTick messages published.")

_last_anomaly = Gauge("layer2_last_anomaly_score", "Last anomaly score emitted.", ["symbol"])
_last_if = Gauge("layer2_last_if_score", "Last IsolationForest score emitted.", ["symbol"])
_last_hst = Gauge("layer2_last_hst_score", "Last Half-Space Trees score emitted.", ["symbol"])
_last_trust = Gauge("layer2_last_input_trust_score", "Last trust score seen by Layer 2.", ["symbol"])

_last_input_lag_ms = Gauge(
    "layer2_last_input_lag_ms",
    "Lag between ValidatedTick timestamp and Layer 2 processing time.",
    ["symbol"],
)

_last_state = Gauge(
    "layer2_system_state",
    "System state encoded as 0=NORMAL,1=CONSERVATIVE,2=DEGRADED,3=HALT.",
)

_STATE_NUM = {"NORMAL": 0.0, "CONSERVATIVE": 1.0, "DEGRADED": 2.0, "HALT": 3.0}

# === PHASE 2: ANOMALY SCORE DECOMPOSITION ===

_anomaly_if_score = Gauge(
    "anomaly_subscore_if",
    "Isolation Forest anomaly subscore [0,1]",
    ["symbol"]
)

_anomaly_hst_score = Gauge(
    "anomaly_subscore_hst",
    "Half-Space Trees anomaly subscore [0,1]",
    ["symbol"]
)

_anomaly_mad_triggered = Gauge(
    "anomaly_mad_guard_active",
    "MAD guard activation state (1=active, 0=inactive)",
    ["symbol"]
)

_anomaly_fused_score = Gauge(
    "anomaly_fused_score",
    "Final fused anomaly score [0,1]",
    ["symbol"]
)

_hmm_regime_state = Gauge(
    "hmm_regime_state",
    "Current HMM regime state (0=low_vol, 1=normal, 2=high_vol)",
    ["symbol"]
)

_hmm_regime_posterior = Gauge(
    "hmm_regime_posterior_prob",
    "HMM posterior probability for each regime",
    ["symbol", "regime"]
)

_hmm_regime_transitions = Counter(
    "hmm_regime_transitions_total",
    "Total regime transitions",
    ["symbol", "from_regime", "to_regime"]
)

_feature_raw_return = Gauge(
    "anomaly_feature_raw_return",
    "Feature: raw log return",
    ["symbol"]
)

_feature_rolling_vol = Gauge(
    "anomaly_feature_rolling_volatility",
    "Feature: rolling volatility (30m RV)",
    ["symbol"]
)

_feature_spread_divergence = Gauge(
    "anomaly_feature_spread_divergence",
    "Feature: spread divergence z-score",
    ["symbol"]
)

_feature_latency_anomaly = Gauge(
    "anomaly_feature_latency_anomaly",
    "Feature: latency anomaly z-score",
    ["symbol"]
)

_feature_volume_anomaly = Gauge(
    "anomaly_feature_volume_anomaly",
    "Feature: volume anomaly z-score",
    ["symbol"]
)

_feature_trust_score = Gauge(
    "anomaly_feature_trust_score",
    "Feature: current trust score (not degradation)",
    ["symbol"]
)

_model_inference_latency = Histogram(
    "anomaly_model_inference_duration_ms",
    "Model inference latency in milliseconds",
    ["model"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 50, 100]
)

_feature_extraction_latency = Histogram(
    "anomaly_feature_extraction_duration_ms",
    "Feature extraction latency in milliseconds",
    ["symbol"],
    buckets=[0.1, 0.5, 1, 2, 5, 10]
)

_anomaly_score_histogram = Histogram(
    "anomaly_score_distribution",
    "Anomaly score distribution",
    ["symbol"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0]
)

_decision_gate_transitions = Counter(
    "decision_gate_state_transitions_total",
    "Decision gate state transitions",
    ["symbol", "from_state", "to_state"]
)

# === PHASE 3: HYBRID SYSTEM METRICS ===

# HST Ensemble component scores
_hst_short_score = Gauge(
    "anomaly_hst_short_score",
    "HST short-term (75s) anomaly score [0,1]",
    ["symbol"]
)

_hst_medium_score = Gauge(
    "anomaly_hst_medium_score",
    "HST medium-term (20min) anomaly score [0,1]",
    ["symbol"]
)

_hst_long_score = Gauge(
    "anomaly_hst_long_score",
    "HST long-term (83min) anomaly score [0,1]",
    ["symbol"]
)

# Statistical Process Control scores
_cusum_score = Gauge(
    "anomaly_cusum_score",
    "CUSUM detector anomaly score [0,1]",
    ["symbol"]
)

_ewma_score = Gauge(
    "anomaly_ewma_score",
    "EWMA detector anomaly score [0,1]",
    ["symbol"]
)

_spc_combined_score = Gauge(
    "anomaly_spc_combined_score",
    "Combined SPC (CUSUM+EWMA) score [0,1]",
    ["symbol"]
)

# Fusion weights (regime-adaptive)
_fusion_if_weight = Gauge(
    "anomaly_fusion_if_weight",
    "Current IF weight in fusion",
    ["symbol"]
)

_fusion_hst_weight = Gauge(
    "anomaly_fusion_hst_weight",
    "Current HST ensemble weight in fusion",
    ["symbol"]
)

_fusion_spc_weight = Gauge(
    "anomaly_fusion_spc_weight",
    "Current SPC weight in fusion",
    ["symbol"]
)

# Circuit breakers
_circuit_breaker_triggers = Counter(
    "anomaly_circuit_breaker_triggers_total",
    "Circuit breaker trigger count",
    ["symbol", "reason"]
)

# IF model source tracking
_if_model_source = Gauge(
    "anomaly_if_model_source",
    "IF model source: 0=none, 1=pretrained, 2=online",
    ["symbol"]
)

_decision_gate_transitions_old = Counter(
    "decision_gate_state_transitions_total_old",
    "Decision gate state transitions",
    ["from_state", "to_state"]
)

_decision_gate_trigger_reason = Counter(
    "decision_gate_trigger_total",
    "Decision gate trigger events by reason",
    ["trigger"]
)

# === PHASE 1: NEW DETECTOR METRICS ===

# Detector-specific scores
_detector_abs_threshold = Gauge(
    "anomaly_detector_abs_threshold",
    "Absolute threshold detector score [0,1]",
    ["symbol"]
)

_detector_trust_passthrough = Gauge(
    "anomaly_detector_trust_passthrough",
    "Trust passthrough detector score [0,1]",
    ["symbol"]
)

# Anomaly reasons (counter)
_anomaly_reason_counter = Counter(
    "anomaly_reason_total",
    "Count of anomaly reasons",
    ["symbol", "reason"]
)


@dataclass
class Layer2Service:
    consumer: KafkaConsumer
    publisher: KafkaJsonPublisher
    engine_by_symbol: dict[str, Layer2ScoringEngine]
    gate_by_symbol: dict[str, DecisionGate]  # Per-symbol gates (not global)
    gate_config: dict[str, float]  # Gate configuration (trust_threshold, anomaly_threshold, etc.)
    missing_data_timeout_s: float = 30.0
    _last_valid_tick_s: float = field(default_factory=time.monotonic, init=False, repr=False)
    _watchdog_in_halt: dict[str, bool] = field(default_factory=dict, init=False, repr=False)  # Per-symbol watchdog
    _last_regime: dict[str, int] = field(default_factory=dict, init=False, repr=False)  # Phase 2
    _last_gate_state: dict[str, str] = field(default_factory=dict, init=False, repr=False)  # Phase 2

    def _enter_watchdog_halt(self, *, symbol: str, now_s: float) -> None:
        if self._watchdog_in_halt.get(symbol, False):
            return

        gate = self.gate_by_symbol.get(symbol)
        if gate is None:
            return

        previous_state = gate.state
        self._watchdog_in_halt[symbol] = True
        gate.update(trust=0.0, anomaly=1.0, regime=0)  # Use regime=0 (low vol, strict) for safety
        _last_state.set(_STATE_NUM.get(gate.state, 3.0))

        if previous_state != "HALT":
            emit_audit_event(
                "layer2.watchdog.timeout",
                source="layer2_anomaly",
                payload={
                    "symbol": symbol,
                    "timeout_s": self.missing_data_timeout_s,
                    "last_valid_tick_s": self._last_valid_tick_s,
                    "triggered_at_s": now_s,
                },
            )

    def _maybe_clear_watchdog(self, *, symbol: str, prev_state: str) -> None:
        gate = self.gate_by_symbol.get(symbol)
        if gate is None:
            return

        if self._watchdog_in_halt.get(symbol, False) and gate.state != "HALT":
            emit_audit_event(
                "layer2.watchdog.recovered",
                source="layer2_anomaly",
                payload={"symbol": symbol, "previous_state": prev_state, "current_state": gate.state},
            )
            self._watchdog_in_halt[symbol] = False

    def _process_validated_tick(self, tick: ValidatedTick) -> None:
        scorer = self.engine_by_symbol.get(tick.symbol)
        if scorer is None:
            scorer = Layer2ScoringEngine(
                symbol=tick.symbol,
                hmm_model_path=os.getenv("HMM_MODEL_PATH", os.path.join("artifacts", "hmm", "model.pkl")),
                anomaly_memory_window=int(os.getenv("L2_ANOMALY_MEMORY_WINDOW", "30")),
            )
            self.engine_by_symbol[tick.symbol] = scorer

        # Get or create per-symbol gate
        gate = self.gate_by_symbol.get(tick.symbol)
        if gate is None:
            gate = DecisionGate(
                trust_threshold=self.gate_config["trust_threshold"],
                anomaly_threshold=self.gate_config["anomaly_threshold"],
                upgrade_streak_required=int(self.gate_config["upgrade_streak_required"]),
                regime_adj=self.gate_config["regime_threshold_adjustment"],
            )
            self.gate_by_symbol[tick.symbol] = gate

        # Score the tick
        start_time = time.perf_counter()
        scores = scorer.score_tick(
            ts_ms=int(tick.timestamp_utc),
            mid_price=float(tick.mid_price),
            trust_score=float(tick.trust_score),
            volume_24h=tick.volume_24h,
            spread=tick.spread,
        )
        total_inference_ms = (time.perf_counter() - start_time) * 1000
        _model_inference_latency.labels(model="total_scoring").observe(total_inference_ms)

        prev_state = gate.state
        system_state = scores.system_state  # Already computed by engine

        _last_state.set(_STATE_NUM.get(system_state, 0.0))
        _last_anomaly.labels(symbol=tick.symbol).set(float(scores.anomaly_score))
        _last_if.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        _last_hst.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        _last_trust.labels(symbol=tick.symbol).set(float(tick.trust_score))
        _last_input_lag_ms.labels(symbol=tick.symbol).set(
            max(0.0, float(int(time.time() * 1000) - int(tick.timestamp_utc)))
        )
        
        # === NEW DETECTOR METRICS ===
        _anomaly_if_score.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        _anomaly_hst_score.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        _anomaly_mad_triggered.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        _anomaly_fused_score.labels(symbol=tick.symbol).set(float(scores.anomaly_score))
        _anomaly_score_histogram.labels(symbol=tick.symbol).observe(float(scores.anomaly_score))
        
        # HMM Regime tracking
        _hmm_regime_state.labels(symbol=tick.symbol).set(int(scores.regime))
        for i, prob in enumerate(scores.regime_posterior):
            _hmm_regime_posterior.labels(symbol=tick.symbol, regime=str(i)).set(float(prob))
        
        # Regime transition detection
        previous_regime = self._last_regime.get(tick.symbol)
        if previous_regime is not None and scores.regime != previous_regime:
            _hmm_regime_transitions.labels(
                symbol=tick.symbol,
                from_regime=str(previous_regime),
                to_regime=str(scores.regime)
            ).inc()
        self._last_regime[tick.symbol] = scores.regime
        
        # Decision gate state transition detection
        if prev_state != system_state:
            _decision_gate_transitions.labels(symbol=tick.symbol, from_state=prev_state, to_state=system_state).inc()
            # Determine trigger reason
            if float(tick.trust_score) < 0.6:
                _decision_gate_trigger_reason.labels(trigger="trust_low").inc()
            if float(scores.anomaly_score) > 0.8:
                _decision_gate_trigger_reason.labels(trigger="anomaly_high").inc()
        
        self._last_gate_state[tick.symbol] = system_state
        
        # === FEATURE VECTOR OBSERVABILITY ===
        _feature_raw_return.labels(symbol=tick.symbol).set(scores.feature_return)
        _feature_rolling_vol.labels(symbol=tick.symbol).set(scores.feature_rv30m)
        _feature_spread_divergence.labels(symbol=tick.symbol).set(scores.feature_spread_bps)
        _feature_latency_anomaly.labels(symbol=tick.symbol).set(0.0)  # Not in new engine
        _feature_volume_anomaly.labels(symbol=tick.symbol).set(scores.feature_volume_ratio)
        _feature_trust_score.labels(symbol=tick.symbol).set(float(tick.trust_score))
        
        # === DETECTOR SCORES ===
        _hst_short_score.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        _hst_medium_score.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        _hst_long_score.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        _cusum_score.labels(symbol=tick.symbol).set(scores.cusum_score)
        _ewma_score.labels(symbol=tick.symbol).set(scores.ewma_score)
        _spc_combined_score.labels(symbol=tick.symbol).set((scores.cusum_score + scores.ewma_score) / 2.0)
        _fusion_if_weight.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        _fusion_hst_weight.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        _fusion_spc_weight.labels(symbol=tick.symbol).set(0.0)  # Deprecated
        
        # === NEW DETECTOR METRICS ===
        _detector_abs_threshold.labels(symbol=tick.symbol).set(scores.absolute_score)
        _detector_trust_passthrough.labels(symbol=tick.symbol).set(0.0)  # Not separate in new engine
        
        # Track anomaly reasons
        if scores.anomaly_score > 0.5 and scores.reason:
            _anomaly_reason_counter.labels(
                symbol=tick.symbol,
                reason=scores.reason
            ).inc()

        out = ScoredTick(
            symbol=tick.symbol,
            asset_class=tick.asset_class,
            primary_exchange=tick.primary_exchange,
            mid_price=tick.mid_price,
            consensus_mid=tick.consensus_mid,
            volume_24h=tick.volume_24h,
            spread=tick.spread,
            trust_score=tick.trust_score,
            sub_scores=tick.sub_scores,
            used_sources=tick.used_sources,
            divergent_sources=tick.divergent_sources,
            timestamp_utc=tick.timestamp_utc,
            tick_hash=tick.tick_hash,
            anomaly_score=float(scores.anomaly_score),
            anomaly_reason=scores.reason,
            if_score=0.0,  # Deprecated
            hst_score=0.0,  # Deprecated
            regime=int(scores.regime),
            regime_posterior=list(scores.regime_posterior),
            system_state=system_state,  # type: ignore[arg-type]
            mad_guard_triggered=False,  # Deprecated
        )

        self.publisher.publish(out.model_dump())
        _scored_out_total.inc()
        self._last_valid_tick_s = time.monotonic()
        self._maybe_clear_watchdog(symbol=tick.symbol, prev_state=prev_state)

    def _check_watchdog(self, *, now_s: Optional[float] = None) -> None:
        current = time.monotonic() if now_s is None else now_s
        if (current - self._last_valid_tick_s) >= self.missing_data_timeout_s:
            self._enter_watchdog_halt(now_s=current)

    def run_forever(self) -> None:
        emit_audit_event(
            "layer2.start",
            source="layer2_anomaly",
            payload={
                "validated_topic": os.getenv("KAFKA_VALIDATED_TOPIC", "market.ticks.validated"),
                "scored_topic": self.publisher.topic,
            },
        )

        try:
            while True:
                try:
                    records = self.consumer.poll(timeout_ms=1000, max_records=10)
                except Exception as poll_ex:
                    logger.error(f"Kafka poll error: {poll_ex}", exc_info=True)
                    continue
                
                if not records:
                    self._check_watchdog()
                    continue

                for _tp, messages in records.items():
                    for msg in messages:
                        _raw_in_total.inc()
                        try:
                            raw = json.loads(msg.value.decode("utf-8"))
                            tick = ValidatedTick.model_validate(raw)
                        except Exception as e:
                            _bad_in_total.inc()
                            emit_audit_event(
                                "layer2.bad_validated_tick",
                                source="layer2_anomaly",
                                payload={"error": repr(e)},
                            )
                            continue

                        try:
                            self._process_validated_tick(tick)
                        except Exception as proc_ex:
                            logger.error(f"Error processing tick: {proc_ex}", exc_info=True)
                        
                        self._check_watchdog(now_s=time.monotonic())
        except Exception as e:
            logger.error(f"Fatal error in consumer loop: {e}", exc_info=True)
            raise
        finally:
            self.publisher.stop()
            self.consumer.close()


def build_service() -> Layer2Service:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
    validated_topic = os.getenv("KAFKA_VALIDATED_TOPIC", "market.ticks.validated")
    group_id = os.getenv("KAFKA_GROUP_ID", f"layer2-anomaly-{int(time.time())}")

    consumer = KafkaConsumer(
        validated_topic,
        bootstrap_servers=bootstrap,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest"),
    )

    pub_cfg = KafkaJsonPublisherConfig.from_env(topic_env="KAFKA_SCORED_TOPIC", default_topic="market.ticks.scored")
    publisher = KafkaJsonPublisher(pub_cfg, client_id="layer2_anomaly")
    publisher.start()

    # Gate configuration (used to create per-symbol gates)
    gate_config = {
        "trust_threshold": float(os.getenv("L2_TRUST_THRESHOLD", "0.60")),
        "anomaly_threshold": float(os.getenv("L2_ANOMALY_THRESHOLD", "0.55")),
        "upgrade_streak_required": int(os.getenv("L2_UPGRADE_STREAK", "10")),
        "regime_threshold_adjustment": float(os.getenv("L2_REGIME_THRESHOLD_ADJUSTMENT", "0.10")),
    }

    return Layer2Service(
        consumer=consumer,
        publisher=publisher,
        engine_by_symbol={},
        gate_by_symbol={},  # Per-symbol gates created on-demand
        gate_config=gate_config,
    )


def main() -> None:
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9103")))
    mark_service_healthy("layer2_anomaly", "layer2")
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()
