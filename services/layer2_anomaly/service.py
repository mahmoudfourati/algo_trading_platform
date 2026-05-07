"""Layer 2 anomaly service.

Consumes ValidatedTick, emits anomaly/system state, and publishes ScoredTick.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from kafka import KafkaConsumer
from prometheus_client import Counter, Gauge

from services.layer1_validated.kafka_json_publisher import KafkaJsonPublisher, KafkaJsonPublisherConfig
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.schemas import ScoredTick, ValidatedTick

from .engine import DecisionGate, Layer2ScoringEngine


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


@dataclass
class Layer2Service:
    consumer: KafkaConsumer
    publisher: KafkaJsonPublisher
    engine_by_symbol: dict[str, Layer2ScoringEngine]
    gate: DecisionGate
    missing_data_timeout_s: float = 30.0
    _last_valid_tick_s: float = field(default_factory=time.monotonic, init=False, repr=False)
    _watchdog_in_halt: bool = field(default=False, init=False, repr=False)

    def _enter_watchdog_halt(self, *, now_s: float) -> None:
        if self._watchdog_in_halt:
            return

        previous_state = self.gate.state
        self._watchdog_in_halt = True
        self.gate.update(trust=0.0, anomaly=1.0)
        _last_state.set(_STATE_NUM.get(self.gate.state, 3.0))
        if previous_state != "HALT":
            emit_audit_event(
                "layer2.watchdog.timeout",
                source="layer2_anomaly",
                payload={
                    "timeout_s": self.missing_data_timeout_s,
                    "last_valid_tick_s": self._last_valid_tick_s,
                    "triggered_at_s": now_s,
                },
            )

    def _maybe_clear_watchdog(self, *, prev_state: str) -> None:
        if self._watchdog_in_halt and self.gate.state != "HALT":
            emit_audit_event(
                "layer2.watchdog.recovered",
                source="layer2_anomaly",
                payload={"previous_state": prev_state, "current_state": self.gate.state},
            )
            self._watchdog_in_halt = False

    def _process_validated_tick(self, tick: ValidatedTick) -> None:
        scorer = self.engine_by_symbol.get(tick.symbol)
        if scorer is None:
            scorer = Layer2ScoringEngine(
                hmm_model_path=os.getenv("HMM_MODEL_PATH", os.path.join("artifacts", "hmm", "model.pkl")),
                if_weight=float(os.getenv("L2_IF_WEIGHT", "0.45")),
                hst_weight=float(os.getenv("L2_HST_WEIGHT", "0.55")),
                mad_floor=float(os.getenv("L2_MAD_FLOOR", "0.65")),
            )
            self.engine_by_symbol[tick.symbol] = scorer

        scores = scorer.score_tick(
            symbol=tick.symbol,
            ts_ms=int(tick.timestamp_utc),
            mid_price=float(tick.mid_price),
            trust_score=float(tick.trust_score),
            volume_24h=tick.volume_24h,
            spread=tick.spread,
        )

        prev_state = self.gate.state
        system_state = self.gate.update(trust=float(tick.trust_score), anomaly=float(scores.anomaly_score))
        _last_state.set(_STATE_NUM.get(system_state, 0.0))
        _last_anomaly.labels(symbol=tick.symbol).set(float(scores.anomaly_score))
        _last_if.labels(symbol=tick.symbol).set(float(scores.if_score))
        _last_hst.labels(symbol=tick.symbol).set(float(scores.hst_score))
        _last_trust.labels(symbol=tick.symbol).set(float(tick.trust_score))
        _last_input_lag_ms.labels(symbol=tick.symbol).set(
            max(0.0, float(int(time.time() * 1000) - int(tick.timestamp_utc)))
        )

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
            if_score=float(scores.if_score),
            hst_score=float(scores.hst_score),
            regime=int(scores.regime),
            regime_posterior=list(scores.regime_posterior),
            system_state=system_state,  # type: ignore[arg-type]
            mad_guard_triggered=bool(scores.mad_guard_triggered),
        )

        self.publisher.publish(out.model_dump())
        _scored_out_total.inc()
        self._last_valid_tick_s = time.monotonic()
        self._maybe_clear_watchdog(prev_state=prev_state)

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
                records = self.consumer.poll(timeout_ms=1000, max_records=10)
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

                        self._process_validated_tick(tick)
                        self._check_watchdog(now_s=time.monotonic())
        finally:
            self.publisher.stop()
            self.consumer.close()


def build_service() -> Layer2Service:
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9103")))

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

    gate = DecisionGate(
        trust_threshold=float(os.getenv("L2_TRUST_THRESHOLD", "0.60")),
        anomaly_threshold=float(os.getenv("L2_ANOMALY_THRESHOLD", "0.80")),
        upgrade_streak_required=int(os.getenv("L2_UPGRADE_STREAK", "10")),
    )

    return Layer2Service(
        consumer=consumer,
        publisher=publisher,
        engine_by_symbol={},
        gate=gate,
    )


def main() -> None:
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()
