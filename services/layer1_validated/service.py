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
from typing import Dict, Iterable, List, Optional

from kafka import KafkaConsumer
from prometheus_client import Counter, Gauge

from services.layer1_consensus.engine import AlignedWindow, ConsensusConfig, ConsensusEngine, TickAligner
from services.layer1_hashlog.hash_chain import HashChainLogger
from services.layer1_trust.scoring import TrustWeights, compute_subscores, compute_t2, compute_trust_score, load_trust_weights
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.schemas import ExchangeId, NormalizedTick, ValidatedTick

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

_last_trust_score = Gauge(
    "layer1_validated_last_trust_score",
    "Most recent computed trust score (last window).",
    ["symbol"],
)


def _parse_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _enabled_exchanges() -> list[ExchangeId]:
    raw = os.getenv("EXCHANGES", "binance,coinbase,kraken")
    xs = _parse_csv(raw)
    return [x for x in xs if x in {"binance", "coinbase", "kraken", "okx", "bybit"}]  # type: ignore[return-value]


def _median_latency_ms(ticks: Iterable[NormalizedTick], *, now_ms: int) -> float:
    # Use window/processing time vs exchange time so carry-forward staleness is penalized.
    latencies = [max(0, int(now_ms) - int(t.exchange_timestamp_ms)) for t in ticks]
    if not latencies:
        return 0.0
    return float(statistics.median(latencies))


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
    liveness: ExchangeLivenessMonitor
    _last_liveness_overdue: Dict[str, float]
    _last_liveness_check_s: float

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
        finally:
            self.hashlog.stop()
            self.publisher.stop()
            self.consumer.close()

    def _process_window(self, window: AlignedWindow) -> None:
        symbol = window.symbol
        by_ex = window.by_ex

        _windows_total.labels(symbol=symbol).inc()
        out = self.consensus.process_aligned(symbol, by_ex)
        if out.consensus_mid is None:
            return

        usable_ticks = [t for ex, t in by_ex.items() if ex in out.used_sources]

        tolerance = abs(out.consensus_mid) * float(self.consensus.config.divergence_tolerance)
        t2 = compute_t2(
            ticks_with_age=window.ticks_with_age,
            consensus_price=out.consensus_mid,
            tolerance=tolerance,
            active_sources=window.active_sources,
        )

        latency_ms = _median_latency_ms(usable_ticks, now_ms=window.window_end_ms)
        spread = _median_spread(usable_ticks)
        volume_24h = _median_volume_24h(usable_ticks)

        # Phase 2.2 pinning refuses mismatched connections, so ticks imply TLS OK.
        tls_ok = True

        # Sequence gaps are not yet fully supported across all exchanges; treat missing as no penalty.
        sequence_gap = None

        previous_hash = self.hashlog.tip
        chain_ok = True  # previous_hash is taken from current tip.

        subscores = compute_subscores(
            tls_ok=tls_ok,
            t2=t2,
            latency_ms=latency_ms,
            sequence_gap=sequence_gap,
            chain_ok=chain_ok,
        )
        trust_score = compute_trust_score(weights=self.weights, subscores=subscores)
        _last_trust_score.labels(symbol=symbol).set(trust_score)

        tick_hash, _ = self.hashlog.append(
            symbol=symbol,
            consensus_mid=out.consensus_mid,
            trust_score=trust_score,
            received_timestamp_ms=window.window_end_ms,
            previous_hash=previous_hash,
        )

        validated = ValidatedTick(
            symbol=symbol,
            mid_price=out.consensus_mid,
            volume_24h=volume_24h,
            spread=spread,
            trust_score=trust_score,
            sub_scores=subscores,
            divergent_sources=out.quarantined_sources,
            timestamp_utc=window.window_end_ms,
            tick_hash=tick_hash,
            liveness=self._last_liveness_overdue or None,
        )

        self.publisher.publish(validated.model_dump())
        _published_total.labels(symbol=symbol).inc()


def build_service() -> Layer1ValidatedService:
    enabled_exchanges = _enabled_exchanges()
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
    raw_topic = os.getenv("KAFKA_RAW_TOPIC", "market.ticks.raw")

    group_id = os.getenv("KAFKA_GROUP_ID", f"layer1-validated-{int(time.time())}")

    consumer = KafkaConsumer(
        raw_topic,
        bootstrap_servers=bootstrap,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET_RESET", "latest"),
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

    return Layer1ValidatedService(
        consumer=consumer,
        publisher=publisher,
        consensus=consensus,
        aligner=aligner,
        weights=weights,
        hashlog=hashlog,
        enabled_exchanges=enabled_exchanges,
        liveness=liveness,
        _last_liveness_overdue={},
        _last_liveness_check_s=0.0,
    )


def main() -> None:
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9102")))
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()
