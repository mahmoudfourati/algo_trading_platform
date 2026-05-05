"""Layer 1 end-to-end trace harness.

Consumes raw ticks, replays alignment/consensus/trust, and correlates with validated ticks.
"""

import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from kafka import KafkaAdminClient, KafkaConsumer
from kafka.admin import NewTopic

from services.layer1_consensus.engine import ConsensusConfig, ConsensusEngine, TickAligner
from services.layer1_trust.scoring import (
    TrustWeights,
    compute_subscores,
    compute_t2,
    compute_trust_score,
    load_trust_weights,
)
from shared.schemas import ExchangeId, NormalizedTick


BOOTSTRAP_SERVER = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
RAW_TOPIC = os.getenv("KAFKA_RAW_TOPIC", "market.ticks.raw")
VALIDATED_TOPIC = os.getenv("KAFKA_VALIDATED_TOPIC", "market.ticks.validated")
AUTO_OFFSET_RESET = os.getenv("KAFKA_AUTO_OFFSET_RESET", "latest")  # latest|earliest
PRIMARY_EXCHANGE = os.getenv("PRIMARY_EXCHANGE", "binance")

MAX_WINDOWS = int(os.getenv("TRACE_MAX_WINDOWS", "12"))
MAX_SECONDS = float(os.getenv("TRACE_MAX_SECONDS", "15"))

ENSURE_TOPICS = os.getenv("KAFKA_ENSURE_TOPICS", "1").strip().lower() in {"1", "true", "yes", "y", "on"}
RAW_PARTITIONS = int(os.getenv("KAFKA_RAW_TOPIC_PARTITIONS", "6"))
VALIDATED_PARTITIONS = int(os.getenv("KAFKA_TOPIC_PARTITIONS", "3"))
REPLICATION_FACTOR = int(os.getenv("KAFKA_TOPIC_REPLICATION_FACTOR", "1"))


def _parse_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _enabled_exchanges() -> list[ExchangeId]:
    raw = os.getenv("EXCHANGES", "binance,coinbase,kraken")
    xs = _parse_csv(raw)
    return [x for x in xs if x in {"binance", "coinbase", "kraken", "okx", "bybit"}]  # type: ignore[return-value]


def ensure_topics() -> None:
    if not ENSURE_TOPICS:
        return

    admin = KafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVER, client_id="trace-layer1-admin")
    try:
        existing = set(admin.list_topics())
        new_topics: List[NewTopic] = []

        if RAW_TOPIC not in existing:
            new_topics.append(
                NewTopic(name=RAW_TOPIC, num_partitions=RAW_PARTITIONS, replication_factor=REPLICATION_FACTOR)
            )

        if VALIDATED_TOPIC not in existing:
            new_topics.append(
                NewTopic(
                    name=VALIDATED_TOPIC,
                    num_partitions=VALIDATED_PARTITIONS,
                    replication_factor=REPLICATION_FACTOR,
                )
            )

        if new_topics:
            admin.create_topics(new_topics=new_topics, validate_only=False)
    finally:
        admin.close()


def _median_latency_ms(ticks: List[NormalizedTick]) -> float:
    latencies = [
        max(0, t.received_timestamp_ms - t.exchange_timestamp_ms)
        for t in ticks
        if getattr(t, "timestamp_source", "exchange") == "exchange"
    ]
    if not latencies:
        return float("inf")
    return float(statistics.median(latencies))


def _median_spread(ticks: List[NormalizedTick]) -> float:
    spreads: List[float] = []
    for t in ticks:
        mid = t.mid
        if mid <= 0:
            continue
        spreads.append(max(0.0, (t.ask - t.bid) / mid))
    if not spreads:
        return 0.0
    return float(statistics.median(spreads))


def _median_volume_24h(ticks: List[NormalizedTick]) -> float:
    vols = [max(0.0, float(t.volume_24h)) for t in ticks]
    if not vols:
        return 0.0
    return float(statistics.median(vols))


def _print(stage: str, payload: Dict[str, Any]) -> None:
    out = {"stage": stage, "ts": int(time.time() * 1000), **payload}
    print(json.dumps(out, separators=(",", ":"), sort_keys=True))


@dataclass
class WindowStats:
    symbol: str
    consensus_mid: float
    used_sources: List[str]
    quarantined_sources: List[str]
    trust_score: float


def _try_pop_validated_for_symbol(
    buffered: List[dict],
    *,
    symbol: str,
) -> Optional[dict]:
    for i, msg in enumerate(buffered):
        if isinstance(msg, dict) and msg.get("symbol") == symbol:
            return buffered.pop(i)
    return None


def _approx_equal(a: float, b: float, *, rel: float = 1e-9, abs_tol: float = 1e-9) -> bool:
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def _try_pop_validated_match(
    buffered: List[dict],
    *,
    symbol: str,
    primary_exchange: str,
    mid_price: float,
    consensus_mid: float,
    trust_score: float,
) -> Optional[dict]:
    for i, msg in enumerate(buffered):
        if not isinstance(msg, dict) or msg.get("symbol") != symbol:
            continue
        if msg.get("primary_exchange") != primary_exchange:
            continue

        m = msg.get("mid_price")
        cm = msg.get("consensus_mid")
        ts = msg.get("trust_score")
        if not isinstance(m, (int, float)) or not isinstance(cm, (int, float)) or not isinstance(ts, (int, float)):
            continue

        if _approx_equal(float(m), float(mid_price), rel=1e-8, abs_tol=1e-8) and _approx_equal(
            float(cm), float(consensus_mid), rel=1e-8, abs_tol=1e-8
        ) and _approx_equal(
            float(ts), float(trust_score), rel=1e-6, abs_tol=1e-6
        ):
            return buffered.pop(i)
    return None


def main() -> None:
    print(f"Bootstrap: {BOOTSTRAP_SERVER}")
    print(f"Raw topic: {RAW_TOPIC}")
    print(f"Validated topic: {VALIDATED_TOPIC}")
    print(f"Offset reset: {AUTO_OFFSET_RESET}")
    print(f"Max windows: {MAX_WINDOWS}")
    print(f"Max seconds: {MAX_SECONDS}")

    ensure_topics()

    enabled_exchanges = _enabled_exchanges()

    consensus_cfg = ConsensusConfig(
        divergence_tolerance=float(os.getenv("CONSENSUS_DIVERGENCE_TOL", "0.003")),
        aggregation_window_ms=int(os.getenv("CONSENSUS_WINDOW_MS", "50")),
        escalate_after=int(os.getenv("CONSENSUS_ESCALATE_AFTER", "3")),
        min_sources_for_consensus=int(os.getenv("CONSENSUS_MIN_SOURCES", "2")),
    )
    consensus = ConsensusEngine(consensus_cfg)
    aligner = TickAligner(window_ms=consensus_cfg.aggregation_window_ms)

    weights: TrustWeights = load_trust_weights()

    raw_group = os.getenv("TRACE_RAW_GROUP_ID", f"trace-raw-{int(time.time())}")
    validated_group = os.getenv("TRACE_VALIDATED_GROUP_ID", f"trace-validated-{int(time.time())}")

    validated_consumer = KafkaConsumer(
        VALIDATED_TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVER,
        group_id=validated_group,
        enable_auto_commit=True,
        auto_offset_reset=AUTO_OFFSET_RESET,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )

    raw_consumer = KafkaConsumer(
        RAW_TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVER,
        group_id=raw_group,
        enable_auto_commit=True,
        auto_offset_reset=AUTO_OFFSET_RESET,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )

    buffered_validated: List[dict] = []
    window_stats: List[WindowStats] = []

    start = time.time()
    processed_windows = 0

    try:
        for msg in raw_consumer:
            if time.time() - start > MAX_SECONDS:
                break

            raw_value = msg.value
            try:
                tick = NormalizedTick.model_validate(raw_value)
            except Exception as e:
                _print(
                    "raw_bad",
                    {
                        "error": repr(e),
                        "raw": raw_value,
                        "partition": msg.partition,
                        "offset": msg.offset,
                    },
                )
                continue

            _print(
                "raw_in",
                {
                    "symbol": tick.symbol,
                    "exchange_id": tick.exchange_id,
                    "mid": tick.mid,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "exchange_ts": tick.exchange_timestamp_ms,
                    "received_ts": tick.received_timestamp_ms,
                    "latency_ms": max(0, tick.received_timestamp_ms - tick.exchange_timestamp_ms),
                    "partition": msg.partition,
                    "offset": msg.offset,
                },
            )

            # Opportunistically drain validated topic.
            polled = validated_consumer.poll(timeout_ms=10, max_records=50)
            for records in polled.values():
                for rec in records:
                    if isinstance(rec.value, dict):
                        buffered_validated.append(rec.value)

            for window in aligner.add(tick):
                symbol = window.symbol
                by_ex = window.by_ex
                aligned_exchanges = sorted(by_ex.keys())
                missing = sorted([ex for ex in enabled_exchanges if ex not in by_ex])

                _print(
                    "aligned_window",
                    {
                        "symbol": symbol,
                        "window_ms": consensus_cfg.aggregation_window_ms,
                        "present": aligned_exchanges,
                        "missing": missing,
                        "by_ex": {
                            ex: {
                                "mid": t.mid,
                                "bid": t.bid,
                                "ask": t.ask,
                                "received_ts": t.received_timestamp_ms,
                            }
                            for ex, t in sorted(by_ex.items())
                        },
                    },
                )

                out = consensus.process_aligned(symbol, by_ex)
                _print(
                    "consensus",
                    {
                        "symbol": symbol,
                        "consensus_mid": out.consensus_mid,
                        "used_sources": out.used_sources,
                        "divergent_sources": out.divergent_sources,
                        "quarantined_sources": out.quarantined_sources,
                        "escalated_sources": out.escalated_sources,
                    },
                )

                if out.consensus_mid is None:
                    continue

                primary_tick = by_ex.get(PRIMARY_EXCHANGE)
                if primary_tick is None or PRIMARY_EXCHANGE not in out.used_sources:
                    _print(
                        "primary_skipped",
                        {
                            "symbol": symbol,
                            "primary_exchange": PRIMARY_EXCHANGE,
                            "used_sources": out.used_sources,
                            "available_sources": sorted(by_ex.keys()),
                        },
                    )
                    continue

                usable_ticks = [primary_tick]

                agreeing_sources = len(out.used_sources)
                tolerance = abs(float(out.consensus_mid)) * float(consensus.config.divergence_tolerance)
                t2 = compute_t2(
                    ticks_with_age=window.ticks_with_age,
                    consensus_price=float(out.consensus_mid),
                    tolerance=tolerance,
                    active_sources=window.active_sources,
                )

                latency_ms = _median_latency_ms(usable_ticks)
                spread = _median_spread(usable_ticks)
                volume_24h = _median_volume_24h(usable_ticks)

                # Mirror services/layer1_validated/service.py assumptions.
                tls_ok = True
                sequence_gap = None
                chain_ok = True

                subscores = compute_subscores(
                    tls_ok=tls_ok,
                    t2=t2,
                    latency_ms=latency_ms,
                    sequence_gap=sequence_gap,
                    chain_ok=chain_ok,
                )
                trust_score = compute_trust_score(weights=weights, subscores=subscores)

                _print(
                    "trust",
                    {
                        "symbol": symbol,
                        "agreeing_sources": agreeing_sources,
                        "t2": t2,
                        "latency_ms_median": latency_ms,
                        "spread_median": spread,
                        "volume_24h_median": volume_24h,
                        "subscores": subscores,
                        "trust_score": trust_score,
                    },
                )

                # Try to show a corresponding validated tick that the real service published.
                # Best-effort match by (symbol, primary_exchange, primary_mid_price, consensus_mid, trust_score).
                # If not found quickly, we still show the next tick for the symbol but label it as unmatched.
                deadline = time.time() + 1.5
                validated_msg = _try_pop_validated_match(
                    buffered_validated,
                    symbol=symbol,
                    primary_exchange=PRIMARY_EXCHANGE,
                    mid_price=float(primary_tick.mid),
                    consensus_mid=float(out.consensus_mid),
                    trust_score=float(trust_score),
                )
                while validated_msg is None and time.time() < deadline:
                    polled = validated_consumer.poll(timeout_ms=100, max_records=50)
                    for records in polled.values():
                        for rec in records:
                            if isinstance(rec.value, dict):
                                buffered_validated.append(rec.value)
                    validated_msg = _try_pop_validated_match(
                        buffered_validated,
                        symbol=symbol,
                        primary_exchange=PRIMARY_EXCHANGE,
                        mid_price=float(primary_tick.mid),
                        consensus_mid=float(out.consensus_mid),
                        trust_score=float(trust_score),
                    )

                if validated_msg is not None:
                    _print("validated_out", {"symbol": symbol, "validated": validated_msg})
                else:
                    fallback = _try_pop_validated_for_symbol(buffered_validated, symbol=symbol)
                    if fallback is not None:
                        _print(
                            "validated_out_unmatched",
                            {
                                "symbol": symbol,
                                "expected": {
                                    "primary_exchange": PRIMARY_EXCHANGE,
                                    "mid_price": float(primary_tick.mid),
                                    "consensus_mid": float(out.consensus_mid),
                                    "trust_score": float(trust_score),
                                },
                                "validated": fallback,
                            },
                        )
                    else:
                        _print(
                            "validated_out_missing",
                            {
                                "symbol": symbol,
                                "expected": {
                                    "primary_exchange": PRIMARY_EXCHANGE,
                                    "mid_price": float(primary_tick.mid),
                                    "consensus_mid": float(out.consensus_mid),
                                    "trust_score": float(trust_score),
                                },
                            },
                        )

                window_stats.append(
                    WindowStats(
                        symbol=symbol,
                        consensus_mid=float(out.consensus_mid),
                        used_sources=[str(x) for x in out.used_sources],
                        quarantined_sources=[str(x) for x in out.quarantined_sources],
                        trust_score=float(trust_score),
                    )
                )

                processed_windows += 1
                if processed_windows >= MAX_WINDOWS:
                    break

            if processed_windows >= MAX_WINDOWS:
                break

    finally:
        raw_consumer.close()
        validated_consumer.close()

    # Summary (kept brief; the detailed per-step output is above).
    by_symbol: Dict[str, List[WindowStats]] = {}
    for ws in window_stats:
        by_symbol.setdefault(ws.symbol, []).append(ws)

    summary: Dict[str, Any] = {
        "processed_windows": len(window_stats),
        "by_symbol": {},
    }

    for symbol, items in by_symbol.items():
        trust_scores = [x.trust_score for x in items]
        used_counts = [len(x.used_sources) for x in items]
        summary["by_symbol"][symbol] = {
            "windows": len(items),
            "used_sources_min": min(used_counts) if used_counts else 0,
            "used_sources_max": max(used_counts) if used_counts else 0,
            "trust_min": min(trust_scores) if trust_scores else None,
            "trust_median": float(statistics.median(trust_scores)) if trust_scores else None,
            "trust_max": max(trust_scores) if trust_scores else None,
        }

    _print("summary", summary)


if __name__ == "__main__":
    main()
