"""Layer 1 validated service.

Consumes raw ticks, aligns windows, runs consensus + trust scoring, and publishes ValidatedTick.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, cast

from kafka import KafkaConsumer
from prometheus_client import Counter, Gauge, Histogram

from services.layer1_consensus.engine import AlignedWindow, ConsensusConfig, ConsensusEngine, TickAligner
from services.layer1_hashlog.hash_chain import HashChainLogger
from services.layer1_trust.scoring import TrustWeights, compute_subscores, compute_t2, compute_trust_score, load_trust_weights
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.service_health import mark_service_healthy
from shared.schemas import ExchangeId, NormalizedTick, ValidatedTick
from shared.tls_health_registry import get_tls_health_registry

from .liveness import ExchangeLivenessMonitor

from .kafka_json_publisher import KafkaJsonPublisher, KafkaJsonPublisherConfig


_raw_ticks_total = Counter(
    "layer1_validated_raw_ticks_total",
    "Total raw ticks consumed and successfully parsed.",
)

_bad_raw_ticks_total = Counter(
    "layer1_validated_bad_raw_ticks_total",
    "Total raw ticks that failed decoding or schema validation.",
)

_windows_total = Counter(
    "layer1_validated_windows_total",
    "Total aligned windows processed (per symbol, per time window).",
    ["symbol"],
)

_published_total = Counter(
    "layer1_validated_published_total",
    "Total validated ticks published.",
    ["symbol"],
)

_primary_source_skipped_total = Counter(
    "layer1_validated_primary_source_skipped_total",
    "Total aligned windows skipped because the configured primary exchange was unavailable or excluded.",
    ["symbol"],
)

_last_trust_score = Gauge(
    "layer1_validated_last_trust_score",
    "Most recent computed trust score (last window).",
    ["symbol"],
)

_last_window_sources = Gauge(
    "layer1_validated_last_window_sources",
    "Number of aligned exchange sources observed in the last processed window.",
    ["symbol"],
)

_last_window_used_sources = Gauge(
    "layer1_validated_last_window_used_sources",
    "Number of exchange sources used in consensus in the last processed window.",
    ["symbol"],
)

_last_window_latency_ms = Gauge(
    "layer1_validated_last_window_latency_ms",
    "Latency from exchange timestamp to Layer1 validated publish time (median across usable ticks).",
    ["symbol"],
)

# TLS/health observability (cached; derived from liveness monitor state)
_tls_exchange_health = Gauge(
    "tls_exchange_health",
    "TLS health of the primary exchange for the last processed window (1=healthy, 0=unhealthy).",
    ["symbol", "exchange_id"],
)
_tls_validation_failures_total = Counter(
    "tls_validation_failures_total",
    "Total number of windows where the primary exchange TLS pin health was unhealthy (derived).",
    ["symbol", "exchange_id"],
)
_missing_tls_pins_total = Counter(
    "missing_tls_pins_total",
    "Total number of windows with missing/invalid TLS pins detected by derived TLS health (best-effort).",
    ["symbol", "exchange_id"],
)

# === PHASE 3: LAYER 1 DEEP TELEMETRY ===

_tick_rejection_reasons = Counter(
    "tick_rejection_total",
    "Tick rejections by reason",
    ["exchange_id", "reason"]  # reason = malformed|stale|duplicate|invalid_price|schema_error
)

_consensus_divergent_sources = Gauge(
    "consensus_divergent_source_count",
    "Number of sources excluded from consensus due to price divergence",
    ["symbol"]
)

_consensus_divergence_magnitude = Gauge(
    "consensus_divergence_max_bps",
    "Maximum price divergence in basis points",
    ["symbol"]
)

_trust_score_histogram = Histogram(
    "trust_score_distribution",
    "Trust score distribution for anomaly detection",
    ["symbol"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]
)

_trust_degradation_events = Counter(
    "trust_degradation_events_total",
    "Count of sudden trust score drops >0.1 in single window",
    ["symbol", "primary_cause"]  # primary_cause = t1|t2|t3|t4|t5|availability
)
_active_exchange_count = Gauge(
    "active_exchange_count",
    "Number of exchange sources observed in the last processed window (used_sources).",
    ["symbol"],
)

_availability_score = Gauge(
    "availability_score",
    "Exchange availability score (active/configured) for the last processed window.",
    ["symbol"],
)

_unhealthy_exchange_count = Gauge(
    "unhealthy_exchange_count",
    "Number of configured exchanges currently marked TLS-unhealthy.",
)

# === TRUST SCORE SUBCOMPONENTS (Phase 1 Observability) ===

_trust_t1_tls = Gauge(
    "trust_subscore_t1_tls",
    "T1: TLS validity subscore [0,1]",
    ["symbol", "exchange_id"]
)

_trust_t2_consensus = Gauge(
    "trust_subscore_t2_consensus",
    "T2: Consensus agreement subscore [0,1]",
    ["symbol"]
)

_trust_t3_freshness = Gauge(
    "trust_subscore_t3_freshness",
    "T3: Latency freshness subscore [0,1]",
    ["symbol"]
)

_trust_t4_sequence = Gauge(
    "trust_subscore_t4_sequence",
    "T4: Sequence integrity subscore [0,1]",
    ["symbol", "exchange_id"]
)

_trust_t5_hashchain = Gauge(
    "trust_subscore_t5_hashchain",
    "T5: Hash chain continuity subscore [0,1]",
    ["symbol"]
)

_trust_t_availability = Gauge(
    "trust_subscore_t_availability",
    "T_availability: Exchange availability subscore [0,1]",
    ["symbol"]
)

_sequence_gap_histogram = Histogram(
    "sequence_gap_distribution",
    "Distribution of sequence gaps for gap analysis",
    ["symbol", "exchange_id"],
    buckets=[1, 2, 3, 5, 10, 20, 50, 100, 500, 1000]
)


def _parse_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _enabled_exchanges() -> list[ExchangeId]:
    raw = os.getenv("EXCHANGES", "binance,bybit,coinbase,kraken,okx")
    xs = _parse_csv(raw)
    return [x for x in xs if x in {"binance", "coinbase", "kraken", "okx", "bybit"}]  # type: ignore[return-value]


def _primary_exchange(enabled_exchanges: list[ExchangeId]) -> ExchangeId:
    configured = os.getenv("PRIMARY_EXCHANGE", "binance")
    if configured in enabled_exchanges:
        return cast(ExchangeId, configured)

    if not enabled_exchanges:
        raise RuntimeError("No enabled exchanges configured")

    emit_audit_event(
        "layer1.validated.primary_exchange.fallback",
        source="layer1_validated",
        payload={
            "configured": configured,
            "fallback": enabled_exchanges[0],
            "enabled_exchanges": enabled_exchanges,
        },
    )
    return enabled_exchanges[0]


def _median_latency_ms(ticks: Iterable[NormalizedTick], *, now_ms: int) -> float:
    # Prefer ticks with a trustworthy exchange timestamp (T3 measures source-time freshness).
    # Receive-time-only feeds (e.g. Kraken) are excluded from the primary calculation.
    tick_list = list(ticks)
    latencies = [
        max(0, int(now_ms) - int(t.exchange_timestamp_ms))
        for t in tick_list
        if getattr(t, "timestamp_source", "exchange") == "exchange"
    ]
    if latencies:
        return float(statistics.median(latencies))

    # Fallback: if every tick in the window is receive-time-only, use receive latency.
    # This avoids returning inf (which collapses T3 to 0.0) when e.g. only Kraken
    # ticks are present. The score will still be lower than a true exchange-timestamped
    # window because receive latency is always >= source latency, but it won't be zero.
    recv_latencies = [
        max(0, int(now_ms) - int(t.received_timestamp_ms))
        for t in tick_list
    ]
    if recv_latencies:
        return float(statistics.median(recv_latencies))

    return float("inf")


def _median_spread(ticks: Iterable[NormalizedTick]) -> float:
    spreads: List[float] = []
    for t in ticks:
        mid = t.mid
        if mid <= 0:
            continue
        spreads.append(max(0.0, (t.ask - t.bid) / mid))
    if not spreads:
        return 0.0
    return float(statistics.median(spreads))


def _median_volume_24h(ticks: Iterable[NormalizedTick]) -> float:
    vols = [max(0.0, float(t.volume_24h)) for t in ticks]
    if not vols:
        return 0.0
    return float(statistics.median(vols))


@dataclass
class Layer1ValidatedService:
    consumer: KafkaConsumer
    publisher: KafkaJsonPublisher
    consensus: ConsensusEngine
    aligner: TickAligner
    weights: TrustWeights
    hashlog: HashChainLogger
    enabled_exchanges: List[ExchangeId]
    primary_exchange: ExchangeId
    liveness: ExchangeLivenessMonitor
    tls_registry: any  # TlsHealthRegistry
    _last_sequence_ids: Dict[Tuple[str, ExchangeId], int]
    _last_liveness_overdue: Dict[str, float]
    _last_liveness_check_s: float
    _last_trust_scores: Dict[str, float]  # For trust degradation detection

    def _compute_sequence_gap(
        self,
        *,
        symbol: str,
        exchange: ExchangeId,
        sequence_id: Optional[int],
    ) -> Optional[int]:
        if sequence_id is None:
            return None

        key = (symbol, exchange)
        current = int(sequence_id)
        previous = self._last_sequence_ids.get(key)
        if previous is None:
            self._last_sequence_ids[key] = current
            return 1

        gap = current - previous
        if gap <= 0:
            emit_audit_event(
                "layer1.validated.sequence.non_monotonic",
                source="layer1_validated",
                payload={
                    "symbol": symbol,
                    "exchange_id": exchange,
                    "previous_sequence_id": previous,
                    "current_sequence_id": current,
                    "computed_gap": gap,
                },
            )
            # Keep the larger previously-seen sequence id to avoid masking replays.
            self._last_sequence_ids[key] = max(previous, current)
            return 10

        self._last_sequence_ids[key] = current
        if gap > 1:
            emit_audit_event(
                "layer1.validated.sequence.gap",
                source="layer1_validated",
                payload={
                    "symbol": symbol,
                    "exchange_id": exchange,
                    "previous_sequence_id": previous,
                    "current_sequence_id": current,
                    "computed_gap": gap,
                },
            )
        return gap

    def run_forever(self) -> None:
        emit_audit_event(
            "layer1.validated.start",
            source="layer1_validated",
            payload={"raw_topic": os.getenv("KAFKA_RAW_TOPIC", "market.ticks.raw"), "validated_topic": self.publisher.topic},
        )

        try:
            for msg in self.consumer:
                try:
                    raw = json.loads(msg.value.decode("utf-8"))
                    tick = NormalizedTick.model_validate(raw)
                except json.JSONDecodeError as e:
                    _bad_raw_ticks_total.inc()
                    _tick_rejection_reasons.labels(exchange_id="unknown", reason="malformed").inc()
                    emit_audit_event(
                        "layer1.validated.bad_raw_tick",
                        source="layer1_validated",
                        payload={"error": repr(e), "reason": "malformed_json"},
                    )
                    continue
                except Exception as e:
                    _bad_raw_ticks_total.inc()
                    # Try to extract exchange_id from raw data for better metrics
                    exchange_id = "unknown"
                    try:
                        if isinstance(raw, dict):
                            exchange_id = raw.get("exchange_id", "unknown")
                    except:
                        pass
                    _tick_rejection_reasons.labels(exchange_id=exchange_id, reason="schema_error").inc()
                    emit_audit_event(
                        "layer1.validated.bad_raw_tick",
                        source="layer1_validated",
                        payload={"error": repr(e), "reason": "schema_validation", "exchange_id": exchange_id},
                    )
                    continue

                _raw_ticks_total.inc()

                self.liveness.record_tick(tick.exchange_id)
                now_s = time.time()
                if now_s - self._last_liveness_check_s >= 1.0:
                    self._last_liveness_overdue = self.liveness.check_all()
                    self._last_liveness_check_s = now_s

                for window in self.aligner.add(tick):
                    self._process_window(window)
                    
                    # Update unhealthy exchange count metric
                    health_snapshot = self.tls_registry.get_all_health()
                    unhealthy_count = sum(1 for ex in self.enabled_exchanges if not health_snapshot.get(ex, True))
                    _unhealthy_exchange_count.set(float(unhealthy_count))
        finally:
            self.hashlog.stop()
            self.publisher.stop()
            self.consumer.close()

    def _process_window(self, window: AlignedWindow) -> None:
        symbol = window.symbol
        by_ex = window.by_ex

        _windows_total.labels(symbol=symbol).inc()
        _last_window_sources.labels(symbol=symbol).set(float(len(by_ex)))
        out = self.consensus.process_aligned(symbol, by_ex)
        if out.consensus_mid is None:
            return

        # NEW: Use consensus price for all downstream layers
        # No longer filter by primary exchange - use all consensus sources
        usable_ticks = [tick for ex, tick in by_ex.items() if ex in out.used_sources]
        
        if not usable_ticks:
            emit_audit_event(
                "layer1.validated.no_usable_ticks",
                source="layer1_validated",
                payload={
                    "symbol": symbol,
                    "available_sources": sorted(str(ex) for ex in by_ex.keys()),
                    "used_sources": out.used_sources,
                },
            )
            return

        tolerance = abs(out.consensus_mid) * float(self.consensus.config.divergence_tolerance)
        t2 = compute_t2(
            ticks_with_age=window.ticks_with_age,
            consensus_price=out.consensus_mid,
            tolerance=tolerance,
            active_sources=window.active_sources,
        )

        latency_ms = _median_latency_ms(usable_ticks, now_ms=window.window_end_ms)
        _last_window_latency_ms.labels(symbol=symbol).set(latency_ms)
        _last_window_used_sources.labels(symbol=symbol).set(float(len(out.used_sources)))

        spread = _median_spread(usable_ticks)
        volume_24h = _median_volume_24h(usable_ticks)

        # TLS health: Check if ANY exchange in consensus has healthy TLS
        # Use pessimistic TLS health (all must be healthy)
        # Security-focused: if ANY exchange has bad TLS, trust should degrade
        tls_states = [getattr(tick, 'tls_ok', False) for tick in usable_ticks]
        tls_ok = all(tls_states) if tls_states else False
        
        # Track TLS health for primary exchange (for metrics continuity)
        primary_tick = by_ex.get(self.primary_exchange)
        if primary_tick:
            primary_tls_ok = getattr(primary_tick, 'tls_ok', False)
            _tls_exchange_health.labels(symbol=symbol, exchange_id=self.primary_exchange).set(1.0 if primary_tls_ok else 0.0)
            if not primary_tls_ok:
                _tls_validation_failures_total.labels(symbol=symbol, exchange_id=self.primary_exchange).inc()
        
        _active_exchange_count.labels(symbol=symbol).set(float(len(out.used_sources)))

        if not tls_ok:
            emit_audit_event(
                "layer1.validated.tls_pin_health.degraded",
                source="layer1_validated",
                payload={"symbol": symbol, "healthy_sources": sum(tls_states), "total_sources": len(tls_states)},
            )

        # Sequence gap tracking for ALL exchanges
        # Compute T4 for each exchange that has sequence IDs, then aggregate
        sequence_gaps = {}
        for exchange, tick in by_ex.items():
            if tick.sequence_id is not None:
                gap = self._compute_sequence_gap(
                    symbol=symbol,
                    exchange=exchange,
                    sequence_id=tick.sequence_id,
                )
                sequence_gaps[exchange] = gap
        
        # Aggregate sequence gap for trust scoring
        # Use the WORST (maximum) gap among all exchanges
        # This is conservative: if ANY exchange has gaps, trust degrades
        if sequence_gaps:
            sequence_gap = max(sequence_gaps.values())
        else:
            sequence_gap = None

        previous_hash = self.hashlog.tip
        chain_ok = True  # previous_hash is taken from current tip.

        # Compute availability score
        active_exchanges_set = set(out.used_sources)
        
        # Exclude exchanges that are silent (detected by liveness monitor)
        # If an exchange hasn't sent a tick in >30s, it's using stale LKV data
        # and should not be counted as "active" for T_availability
        for silent_exchange in self._last_liveness_overdue.keys():
            active_exchanges_set.discard(silent_exchange)
        
        configured_exchanges_set = set(self.enabled_exchanges)
        
        subscores = compute_subscores(
            tls_ok=tls_ok,
            t2=t2,
            latency_ms=latency_ms,
            sequence_gap=sequence_gap,
            chain_ok=chain_ok,
            active_exchanges=active_exchanges_set,
            configured_exchanges=configured_exchanges_set,
        )
        
        # Update availability metric
        availability = subscores.get("T_availability", 1.0)
        _availability_score.labels(symbol=symbol).set(availability)
        
        trust_score = compute_trust_score(weights=self.weights, subscores=subscores)
        _last_trust_score.labels(symbol=symbol).set(trust_score)
        
        # === EXPORT TRUST SUBCOMPONENTS (Phase 1 Observability) ===
        _trust_t1_tls.labels(symbol=symbol, exchange_id=sequence_exchange).set(subscores["T1"])
        _trust_t2_consensus.labels(symbol=symbol).set(subscores["T2"])
        _trust_t3_freshness.labels(symbol=symbol).set(subscores["T3"])
        _trust_t4_sequence.labels(symbol=symbol, exchange_id=sequence_exchange).set(subscores["T4"])
        _trust_t5_hashchain.labels(symbol=symbol).set(subscores["T5"])
        _trust_t_availability.labels(symbol=symbol).set(subscores.get("T_availability", 1.0))
        
        # === TRUST SCORE HISTOGRAM ===
        _trust_score_histogram.labels(symbol=symbol).observe(trust_score)
        
        # === DETECT TRUST DEGRADATION ===
        previous_trust = self._last_trust_scores.get(symbol, trust_score)
        if previous_trust - trust_score > 0.1:  # >10% drop
            # Identify primary cause (component with lowest score)
            primary_cause = min(subscores.items(), key=lambda x: x[1])[0]
            _trust_degradation_events.labels(symbol=symbol, primary_cause=primary_cause).inc()
            emit_audit_event(
                "layer1.validated.trust_degradation",
                source="layer1_validated",
                payload={
                    "symbol": symbol,
                    "previous_trust": previous_trust,
                    "current_trust": trust_score,
                    "drop": previous_trust - trust_score,
                    "primary_cause": primary_cause,
                    "subscores": subscores
                }
            )
        self._last_trust_scores[symbol] = trust_score
        
        # === CONSENSUS DIVERGENCE DETAILS ===
        _consensus_divergent_sources.labels(symbol=symbol).set(len(out.divergent_sources))
        if out.divergent_sources:
            max_divergence_bps = max([
                abs(by_ex[ex].mid - out.consensus_mid) / out.consensus_mid * 10000
                for ex in out.divergent_sources
                if ex in by_ex
            ])
            _consensus_divergence_magnitude.labels(symbol=symbol).set(max_divergence_bps)
        else:
            _consensus_divergence_magnitude.labels(symbol=symbol).set(0.0)
        
        # === SEQUENCE GAP HISTOGRAM ===
        if sequence_gap:
            _sequence_gap_histogram.labels(symbol=symbol, exchange_id=sequence_exchange).observe(sequence_gap)

        # NEW: Build execution venue prices map for Layer 5 divergence checking
        execution_venue_prices = {ex: tick.mid for ex, tick in by_ex.items()}

        tick_hash, _ = self.hashlog.append(
            symbol=symbol,
            primary_exchange=self.primary_exchange,  # Keep for backward compatibility
            primary_mid_price=out.consensus_mid,  # Use consensus price
            consensus_mid=out.consensus_mid,
            used_sources=out.used_sources,
            divergent_sources=out.divergent_sources,
            trust_score=trust_score,
            received_timestamp_ms=window.window_end_ms,
            previous_hash=previous_hash,
        )

        validated = ValidatedTick(
            symbol=symbol,
            primary_exchange=self.primary_exchange,  # Deprecated but kept for compatibility
            mid_price=out.consensus_mid,  # NEW: Use consensus price for all downstream layers
            consensus_mid=out.consensus_mid,
            execution_venue_prices=execution_venue_prices,  # NEW: For execution-time divergence checking
            volume_24h=volume_24h,
            spread=spread,
            trust_score=trust_score,
            sub_scores=subscores,
            used_sources=out.used_sources,
            divergent_sources=out.divergent_sources,
            timestamp_utc=window.window_end_ms,
            tick_hash=tick_hash,
            liveness=self._last_liveness_overdue or None,
        )

        self.publisher.publish(validated.model_dump())
        _published_total.labels(symbol=symbol).inc()


def build_service() -> Layer1ValidatedService:
    enabled_exchanges = _enabled_exchanges()
    primary_exchange = _primary_exchange(enabled_exchanges)
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
    raw_topic = os.getenv("KAFKA_RAW_TOPIC", "market.ticks.raw")

    group_id = os.getenv("KAFKA_GROUP_ID", "layer1-validated")

    consumer = KafkaConsumer(
        raw_topic,
        bootstrap_servers=bootstrap,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest"),
    )

    pub_cfg = KafkaJsonPublisherConfig.from_env(topic_env="KAFKA_VALIDATED_TOPIC", default_topic="market.ticks.validated")
    publisher = KafkaJsonPublisher(pub_cfg, client_id="layer1_validated")
    publisher.start()

    weights = load_trust_weights()

    consensus_cfg = ConsensusConfig(
        divergence_tolerance=float(os.getenv("CONSENSUS_DIVERGENCE_TOL", "0.003")),
        aggregation_window_ms=int(os.getenv("CONSENSUS_WINDOW_MS", "50")),
        escalate_after=int(os.getenv("CONSENSUS_ESCALATE_AFTER", "3")),
        min_sources_for_consensus=int(os.getenv("CONSENSUS_MIN_SOURCES", "2")),
    )

    consensus = ConsensusEngine(consensus_cfg)
    aligner = TickAligner(window_ms=consensus_cfg.aggregation_window_ms)

    log_path = os.getenv("HASH_CHAIN_LOG_PATH", os.path.join("logs", "layer1_hash_chain.jsonl"))
    hashlog = HashChainLogger(path=log_path)
    hashlog.start()

    def _audit(event_type: str, payload: Dict) -> None:
        emit_audit_event(event_type, source="layer1_validated", payload=payload)

    liveness = ExchangeLivenessMonitor(
        sources=[str(x) for x in enabled_exchanges],
        audit_fn=_audit,
    )
    
    tls_registry = get_tls_health_registry()

    return Layer1ValidatedService(
        consumer=consumer,
        publisher=publisher,
        consensus=consensus,
        aligner=aligner,
        weights=weights,
        hashlog=hashlog,
        enabled_exchanges=enabled_exchanges,
        primary_exchange=primary_exchange,
        liveness=liveness,
        tls_registry=tls_registry,
        _last_sequence_ids={},
        _last_liveness_overdue={},
        _last_liveness_check_s=0.0,
        _last_trust_scores={},  # Initialize trust score tracking
    )


def main() -> None:
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9102")))
    mark_service_healthy("layer1_validated", "layer1")
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()
