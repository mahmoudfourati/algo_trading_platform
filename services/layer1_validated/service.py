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
from prometheus_client import Counter, Gauge

from services.layer1_consensus.engine import AlignedWindow, ConsensusConfig, ConsensusEngine, TickAligner
from services.layer1_hashlog.hash_chain import HashChainLogger
from services.layer1_trust.scoring import TrustWeights, compute_subscores, compute_t2, compute_trust_score, load_trust_weights
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
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
                except Exception as e:
                    _bad_raw_ticks_total.inc()
                    emit_audit_event(
                        "layer1.validated.bad_raw_tick",
                        source="layer1_validated",
                        payload={"error": repr(e)},
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

        primary_tick = by_ex.get(self.primary_exchange)
        if primary_tick is None or self.primary_exchange not in out.used_sources:
            _primary_source_skipped_total.labels(symbol=symbol).inc()
            emit_audit_event(
                "layer1.validated.primary_source_skipped",
                source="layer1_validated",
                payload={
                    "symbol": symbol,
                    "primary_exchange": self.primary_exchange,
                    "used_sources": out.used_sources,
                    "available_sources": sorted(str(ex) for ex in by_ex.keys()),
                },
            )
            return

        usable_ticks = [primary_tick]

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

        # TLS health from the primary tick (stamped by the adapter after pin verification).
        # The adapter stamps tls_ok on each tick after checking the pin, so we read the
        # actual verification result that traveled through Kafka.
        tls_ok = getattr(primary_tick, 'tls_ok', False)  # Default to False if field missing
        _tls_exchange_health.labels(symbol=symbol, exchange_id=self.primary_exchange).set(1.0 if tls_ok else 0.0)
        _active_exchange_count.labels(symbol=symbol).set(float(len(out.used_sources)))

        if not tls_ok:
            _tls_validation_failures_total.labels(symbol=symbol, exchange_id=self.primary_exchange).inc()
            emit_audit_event(
                "layer1.validated.tls_pin_health.unhealthy",
                source="layer1_validated",
                payload={"symbol": symbol, "exchange_id": self.primary_exchange},
            )

        sequence_gap = self._compute_sequence_gap(
            symbol=symbol,
            exchange=self.primary_exchange,
            sequence_id=primary_tick.sequence_id,
        )

        previous_hash = self.hashlog.tip
        chain_ok = True  # previous_hash is taken from current tip.

        # Compute availability score
        active_exchanges_set = set(out.used_sources)
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

        tick_hash, _ = self.hashlog.append(
            symbol=symbol,
            primary_exchange=self.primary_exchange,
            primary_mid_price=primary_tick.mid,
            consensus_mid=out.consensus_mid,
            used_sources=out.used_sources,
            divergent_sources=out.divergent_sources,
            trust_score=trust_score,
            received_timestamp_ms=window.window_end_ms,
            previous_hash=previous_hash,
        )

        validated = ValidatedTick(
            symbol=symbol,
            primary_exchange=self.primary_exchange,
            mid_price=primary_tick.mid,
            consensus_mid=out.consensus_mid,
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
    )


def main() -> None:
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9102")))
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()
