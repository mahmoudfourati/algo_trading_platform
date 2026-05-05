"""Layer 1 end-to-end soak test + report.

Runs exchange adapters locally, processes windows through alignment+consensus+trust+hash-chain,
and writes a Markdown report under artifacts/reports/ with explicit measured-vs-assumed semantics.
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import sys
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# Allow running as `python scripts/layer1_e2e_test.py` from repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from services.layer1_consensus.engine import (  # noqa: E402
    LIVENESS_THRESHOLD_MS,
    LKV_STALENESS_MS,
    ConsensusConfig,
    ConsensusEngine,
    TickAligner,
)
from services.layer1_hashlog.hash_chain import HashChainLogger, verify_hash_chain  # noqa: E402
from services.layer1_ingestion.adapters.binance import BinanceAdapter  # noqa: E402
from services.layer1_ingestion.adapters.bybit import BybitAdapter  # noqa: E402
from services.layer1_ingestion.adapters.coinbase import CoinbaseAdapter  # noqa: E402
from services.layer1_ingestion.adapters.kraken import KrakenAdapter  # noqa: E402
from services.layer1_ingestion.adapters.okx import OkxAdapter  # noqa: E402
from services.layer1_trust.scoring import (  # noqa: E402
    HALF_LIFE_MS,
    T2_HALF_LIFE_MS,
    TrustWeights,
    compute_subscores,
    compute_t2,
    compute_trust_score,
    load_trust_weights,
)
from services.layer1_validated.liveness import (  # noqa: E402
    EXPECTED_INTERVALS_MS,
    SILENCE_MULTIPLIER,
    ExchangeLivenessMonitor,
)
from shared.audit import emit_audit_event  # noqa: E402
from shared.schemas import ExchangeId, NormalizedTick  # noqa: E402


PRIMARY_EXCHANGE = os.getenv("PRIMARY_EXCHANGE", "binance")


def _median(xs: Iterable[float]) -> float:
    values = list(xs)
    return float(statistics.median(values)) if values else 0.0


def _mean(xs: Iterable[float]) -> float:
    values = list(xs)
    return float(statistics.mean(values)) if values else 0.0


def _p(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    idx = min(len(xs) - 1, max(0, int(round((len(xs) - 1) * float(p)))))
    return float(xs[idx])


def _hist_counts(values: list[int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for v in values:
        out[int(v)] = out.get(int(v), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: kv[0]))


def _fmt_int(x: float) -> str:
    return f"{int(round(float(x))):d}"


def _fmt_pct(num: int, den: int) -> str:
    if den <= 0:
        return "0.0%"
    return f"{(float(num) / float(den) * 100.0):.1f}%"


def _table_kv(rows: list[tuple[str, Any]]) -> str:
    lines = ["| Key | Value |", "|-----|-------|"]
    for k, v in rows:
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def _median_latency_ms(ticks: list[NormalizedTick], *, now_ms: int) -> float:
    latencies = [
        max(0, int(now_ms) - int(t.exchange_timestamp_ms))
        for t in ticks
        if getattr(t, "timestamp_source", "exchange") == "exchange"
    ]
    return float(statistics.median(latencies)) if latencies else float("inf")


def _median_spread(ticks: list[NormalizedTick]) -> float:
    spreads: list[float] = []
    for t in ticks:
        mid = float(t.mid)
        if mid > 0:
            spreads.append(max(0.0, (float(t.ask) - float(t.bid)) / mid))
    return float(statistics.median(spreads)) if spreads else 0.0


def _median_volume_24h(ticks: list[NormalizedTick]) -> float:
    vols = [max(0.0, float(t.volume_24h)) for t in ticks]
    return float(statistics.median(vols)) if vols else 0.0


class Metrics:
    def __init__(self, *, sources: list[str], symbols: list[str]):
        self.start_time = time.time()
        self.sources = list(sources)
        self.symbols = list(symbols)

        # Ingestion
        self.tick_count: dict[str, int] = defaultdict(int)
        self.tick_dropped: int = 0
        self.last_arrival_ms: dict[str, float] = defaultdict(float)
        self.arrival_gaps_ms: dict[str, list[float]] = defaultdict(list)

        self.last_exchange_ts_ms: dict[str, int] = {}
        self.exchange_ts_gaps_ms: dict[str, list[float]] = defaultdict(list)
        self.exchange_ts_out_of_order: dict[str, int] = defaultdict(int)
        self.exchange_ts_total: dict[str, int] = defaultdict(int)

        # Alignment
        self.windows_emitted = 0
        self.window_real_sources: list[int] = []
        self.window_lkv_filled_sources: list[int] = []
        self.window_total_sources: list[int] = []
        self.window_active_sources: list[int] = []
        self.lkv_age_ms: list[float] = []
        self.lkv_fill_by_source: dict[str, int] = defaultdict(int)

        # Consensus
        self.windows_true_consensus = 0
        self.windows_degraded_single_source = 0
        self.windows_no_consensus = 0
        self.windows_with_any_quarantine = 0
        self.used_sources_count: list[int] = []
        self.quarantined_by_source: dict[str, int] = defaultdict(int)
        self.divergent_by_source: dict[str, int] = defaultdict(int)
        self.escalated_by_source: dict[str, int] = defaultdict(int)
        self.divergence_events = 0

        # Trust
        self.t1_scores: list[float] = []
        self.t2_scores: list[float] = []
        self.t3_scores: list[float] = []
        self.t4_scores: list[float] = []
        self.t5_scores: list[float] = []
        self.trust_scores: list[float] = []
        self.latency_ms_median: list[float] = []
        self.spread_median: list[float] = []
        self.volume_24h_median: list[float] = []

        # Hash-chain
        self.hashchain_appends = 0
        self.hashchain_errors = 0

        # Liveness
        self.liveness_alerts: list[dict] = []
        self.liveness_recoveries: list[dict] = []

    def record_tick(self, source: str, tick: NormalizedTick) -> None:
        now = time.time() * 1000

        # Arrival-time gaps (local process time)
        if self.last_arrival_ms[source] > 0:
            self.arrival_gaps_ms[source].append(now - self.last_arrival_ms[source])
        self.last_arrival_ms[source] = now

        self.tick_count[source] += 1

        # Event-time gaps (exchange timestamps)
        self.exchange_ts_total[source] += 1
        ex_ts = int(tick.exchange_timestamp_ms)
        last = self.last_exchange_ts_ms.get(source)
        if last is not None:
            if ex_ts >= last:
                self.exchange_ts_gaps_ms[source].append(float(ex_ts - last))
            else:
                self.exchange_ts_out_of_order[source] += 1
        self.last_exchange_ts_ms[source] = ex_ts

    def record_alignment(self, window) -> None:
        self.windows_emitted += 1

        real_sources = 0
        lkv_sources = 0
        for t, age_ms in window.ticks_with_age:
            if float(age_ms) <= 0.0:
                real_sources += 1
            else:
                lkv_sources += 1
                self.lkv_age_ms.append(float(age_ms))
                self.lkv_fill_by_source[str(t.exchange_id)] += 1

        self.window_real_sources.append(int(real_sources))
        self.window_lkv_filled_sources.append(int(lkv_sources))
        self.window_total_sources.append(int(real_sources + lkv_sources))
        self.window_active_sources.append(int(len(window.active_sources)))

    def record_consensus(self, out, *, min_sources_for_consensus: int) -> None:
        used = int(len(out.used_sources))
        self.used_sources_count.append(used)

        if used >= int(min_sources_for_consensus):
            self.windows_true_consensus += 1
        elif used == 1:
            self.windows_degraded_single_source += 1
        else:
            self.windows_no_consensus += 1

        if out.quarantined_sources:
            self.windows_with_any_quarantine += 1
        for ex in out.quarantined_sources:
            self.quarantined_by_source[str(ex)] += 1
        for ex in out.divergent_sources:
            self.divergent_by_source[str(ex)] += 1
        for ex in out.escalated_sources:
            self.escalated_by_source[str(ex)] += 1

        if out.divergent_sources:
            self.divergence_events += 1

    def record_trust(
        self,
        *,
        subscores: dict[str, float],
        trust: float,
        latency_ms: float,
        spread: float,
        volume_24h: float,
    ) -> None:
        self.t1_scores.append(float(subscores.get("T1", 0.0)))
        self.t2_scores.append(float(subscores.get("T2", 0.0)))
        self.t3_scores.append(float(subscores.get("T3", 0.0)))
        self.t4_scores.append(float(subscores.get("T4", 0.0)))
        self.t5_scores.append(float(subscores.get("T5", 0.0)))
        self.trust_scores.append(float(trust))

        self.latency_ms_median.append(float(latency_ms))
        self.spread_median.append(float(spread))
        self.volume_24h_median.append(float(volume_24h))


def _score_row(name: str, values: list[float]) -> str:
    if not values:
        return f"| {name} | — | — | — | — | — |"
    return (
        f"| {name}"
        f" | {_p(values, 0.05):.3f}"
        f" | {_median(values):.3f}"
        f" | {_mean(values):.3f}"
        f" | {_p(values, 0.95):.3f}"
        f" | {min(values):.3f}–{max(values):.3f} |"
    )


def generate_report(
    *,
    m: Metrics,
    duration_s: int,
    output_dir: Path,
    hashchain_ok: bool,
    hashchain_msg: str,
    hash_path: Path,
    consensus_cfg: ConsensusConfig,
    weights: TrustWeights,
) -> Path:
    elapsed = max(0.001, time.time() - m.start_time)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ts_slug = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"layer1_e2e_{ts_slug}.md"

    # Ingestion table
    source_rows: list[str] = []
    for src in m.sources:
        count = int(m.tick_count[src])
        rate = round(count / elapsed, 2)

        arrival = m.arrival_gaps_ms[src]
        arrival_p50 = _fmt_int(_median(arrival)) if arrival else "—"
        arrival_p95 = _fmt_int(_p(arrival, 0.95)) if arrival else "—"

        event = m.exchange_ts_gaps_ms[src]
        event_p50 = _fmt_int(_median(event)) if event else "—"
        event_p95 = _fmt_int(_p(event, 0.95)) if event else "—"

        ooo = int(m.exchange_ts_out_of_order.get(src, 0))
        total = int(m.exchange_ts_total.get(src, 0))
        ooo_pct = _fmt_pct(ooo, max(1, total))

        source_rows.append(
            "| {src:<10} | {count:>6} | {rate:>8} | {arrival_p50:>14} | {arrival_p95:>14} | {event_p50:>14} | {event_p95:>14} | {ooo:>5} ({ooo_pct}) |".format(
                src=src,
                count=count,
                rate=rate,
                arrival_p50=arrival_p50,
                arrival_p95=arrival_p95,
                event_p50=event_p50,
                event_p95=event_p95,
                ooo=ooo,
                ooo_pct=ooo_pct,
            )
        )

    source_table = "\n".join(source_rows)

    total_windows = int(m.windows_emitted)
    used_hist = _hist_counts(m.used_sources_count)
    used_hist_table = "\n".join(
        ["| used_sources | windows | share |", "|------------:|--------:|------:|"]
        + [
            f"| {k:>11} | {v:>7} | {_fmt_pct(v, total_windows)} |"
            for k, v in used_hist.items()
        ]
    )

    lkv_age_note = (
        f"P50={_fmt_int(_median(m.lkv_age_ms))}ms, P95={_fmt_int(_p(m.lkv_age_ms, 0.95))}ms, max={_fmt_int(max(m.lkv_age_ms))}ms"
        if m.lkv_age_ms
        else "—"
    )

    total_lkv_fills = int(sum(m.lkv_fill_by_source.values()))
    if total_lkv_fills > 0:
        lkv_fill_table = "\n".join(
            [
                "| Source | LKV fills | Share |",
                "|--------|---------:|------:|",
            ]
            + [
                f"| {src} | {int(m.lkv_fill_by_source.get(src, 0))} | {_fmt_pct(int(m.lkv_fill_by_source.get(src, 0)), total_lkv_fills)} |"
                for src in m.sources
            ]
        )
    else:
        lkv_fill_table = "_No LKV-filled ticks were observed._"

    consensus_source_table = "\n".join(
        [
            "| Source | Quarantined | Divergent | Escalated |",
            "|--------|-----------:|----------:|----------:|",
        ]
        + [
            "| {src} | {q} | {d} | {e} |".format(
                src=src,
                q=int(m.quarantined_by_source.get(src, 0)),
                d=int(m.divergent_by_source.get(src, 0)),
                e=int(m.escalated_by_source.get(src, 0)),
            )
            for src in m.sources
        ]
    )

    consensus_cfg_table = _table_kv(
        [
            ("aggregation_window_ms", consensus_cfg.aggregation_window_ms),
            ("divergence_tolerance", consensus_cfg.divergence_tolerance),
            ("min_sources_for_consensus", consensus_cfg.min_sources_for_consensus),
            ("escalate_after", consensus_cfg.escalate_after),
            ("LKV_STALENESS_MS", LKV_STALENESS_MS),
            ("LIVENESS_THRESHOLD_MS", LIVENESS_THRESHOLD_MS),
            ("T2_HALF_LIFE_MS", T2_HALF_LIFE_MS),
            ("T3_HALF_LIFE_MS", HALF_LIFE_MS),
        ]
    )

    trust_weight_table = _table_kv(
        [
            ("w1_tls", weights.w1_tls),
            ("w2_consensus", weights.w2_consensus),
            ("w3_freshness", weights.w3_freshness),
            ("w4_sequence", weights.w4_sequence),
            ("w5_hash_chain", weights.w5_hash_chain),
        ]
    )

    liveness_cfg_table = _table_kv(
        [("silence_multiplier", SILENCE_MULTIPLIER)]
        + [(f"expected_interval_ms[{k}]", v) for k, v in sorted(EXPECTED_INTERVALS_MS.items())]
    )

    silent_lines = (
        "\n".join(
            f"- `{a['source']}` silent for {a['silence_ms']:.0f} ms at t+{a['elapsed_s']:.0f}s"
            for a in m.liveness_alerts[:50]
        )
        if m.liveness_alerts
        else "_No liveness silent events during the run._"
    )
    recovered_lines = (
        "\n".join(
            f"- `{a['source']}` recovered after {a['silent_ms']:.0f} ms at t+{a['elapsed_s']:.0f}s"
            for a in m.liveness_recoveries[:50]
        )
        if m.liveness_recoveries
        else "_No liveness recovery events during the run._"
    )

    hc_status = "✅ OK" if hashchain_ok else f"❌ {hashchain_msg}"

    report = f"""# Layer 1 End-to-End Test Report

**Generated:** {now_utc}  
**Duration:** {int(round(elapsed))} s (requested: {duration_s} s)  
**Symbols:** {', '.join(m.symbols)}  
**Sources:** {', '.join(m.sources)}  
**Host:** {platform.platform()}  

---

## 0. Test Configuration (what this run measures)

This script runs **Layer 1 locally** (adapters → aligner → consensus → trust → hash-chain) and produces a report.

Measured:
- Per-exchange tick ingestion rates and gaps (both **arrival-time** and **exchange-timestamp** based).
- Alignment behavior (window sizes, LKV fill rate and LKV age distribution, active-source sizes).
- Consensus behavior (true consensus vs degraded, quarantine/divergence/escalation counts).
- Trust scoring outputs (T1..T5 and weighted trust), plus the latency/spread/volume aggregates emitted downstream.
- Liveness silent/recovered events emitted by the liveness monitor.
- Hash-chain continuity **verified end-to-end** at the end of the run.

Not measured / intentionally assumed in this harness:
- Sequence integrity (exchange `sequence_id` is not consistently available; T4 is treated as “no penalty”).
- Per-window TLS state (TLS pinning is enforced in adapters; no explicit per-window TLS flag exists).

Consensus / alignment constants:

{consensus_cfg_table}

---

## 1. Tick Ingestion Summary

| Source     |  Ticks | Ticks/sec | Arrival P50 (ms) | Arrival P95 (ms) | Event-time P50 (ms) | Event-time P95 (ms) | OOO |
|------------|-------:|----------:|-----------------:|-----------------:|--------------------:|--------------------:|----:|
{source_table}

Queue drops (process overloaded): **{m.tick_dropped}**

---

## 2. Alignment (TickAligner) Summary

| Metric | Value |
|--------|-------|
| Windows emitted | {total_windows} |
| Real sources/window (P50 / P95) | {_median(m.window_real_sources):.1f} / {_p([float(x) for x in m.window_real_sources], 0.95):.1f} |
| LKV-filled sources/window (P50 / P95) | {_median(m.window_lkv_filled_sources):.1f} / {_p([float(x) for x in m.window_lkv_filled_sources], 0.95):.1f} |
| Total sources/window (P50 / P95) | {_median(m.window_total_sources):.1f} / {_p([float(x) for x in m.window_total_sources], 0.95):.1f} |
| Active sources/window (P50 / P95) | {_median(m.window_active_sources):.1f} / {_p([float(x) for x in m.window_active_sources], 0.95):.1f} |
| LKV age (filled ticks) | {lkv_age_note} |

LKV fills by source:

{lkv_fill_table}

---

## 3. Consensus (ConsensusEngine) Summary

| Metric | Value |
|--------|-------|
| True consensus windows (>= {consensus_cfg.min_sources_for_consensus} sources) | {m.windows_true_consensus} ({_fmt_pct(m.windows_true_consensus, total_windows)}) |
| Degraded single-source windows | {m.windows_degraded_single_source} ({_fmt_pct(m.windows_degraded_single_source, total_windows)}) |
| No-consensus windows | {m.windows_no_consensus} ({_fmt_pct(m.windows_no_consensus, total_windows)}) |
| Windows with any quarantined source | {m.windows_with_any_quarantine} ({_fmt_pct(m.windows_with_any_quarantine, total_windows)}) |
| Divergence events (any) | {m.divergence_events} ({_fmt_pct(m.divergence_events, total_windows)}) |

Used-sources distribution:

{used_hist_table}

Per-source quarantine/divergence/escalation counts:

{consensus_source_table}

---

## 4. Trust Scoring (T1–T5)

Trust weights:

{trust_weight_table}

| Sub-score | P5 | Median | Mean | P95 | Range |
|----------|---:|------:|----:|---:|------:|
{_score_row('T1 (TLS validity; assumed via pinning)', m.t1_scores)}
{_score_row('T2 (agreement; freshness-weighted)', m.t2_scores)}
{_score_row('T3 (freshness from latency_ms vs exchange_ts)', m.t3_scores)}
{_score_row('T4 (sequence integrity; not measured)', m.t4_scores)}
{_score_row('T5 (hash-chain; runtime-assumed)', m.t5_scores)}
{_score_row('Overall trust', m.trust_scores)}

Underlying window aggregates (median-of-usable-ticks):

| Metric | P50 | P95 | Notes |
|--------|----:|----:|-------|
| latency_ms | {_median(m.latency_ms_median):.1f} | {_p(m.latency_ms_median, 0.95):.1f} | T3 half-life={HALF_LIFE_MS}ms (steep) |
| spread (relative) | {_median(m.spread_median):.6f} | {_p(m.spread_median, 0.95):.6f} | not used in trust formula |
| volume_24h | {_median(m.volume_24h_median):.1f} | {_p(m.volume_24h_median, 0.95):.1f} | used for weighted median consensus |

---

## 5. Liveness Monitor (ExchangeLivenessMonitor)

Liveness config:

{liveness_cfg_table}

Silent events:

{silent_lines}

Recovered events:

{recovered_lines}

---

## 6. Hash Chain Integrity

| Metric | Value |
|--------|-------|
| Appends | {m.hashchain_appends} |
| Append-time errors | {m.hashchain_errors} |
| End-to-end verify | {hc_status} |
| Hash log path | {hash_path} |

---

## 7. Non-misleading Notes (important)

- “Arrival gaps” are based on this process’s clock; “Event-time gaps” use exchange timestamps and are usually more meaningful.
- “True consensus” is counted only when `used_sources >= min_sources_for_consensus`.
- T4 is shown but is **not measured** in this phase because `sequence_id` is not populated across sources.
- T1 is treated as OK because adapters enforce TLS pinning; if pinning fails, the adapter should not stream ticks.
- T5 per-window is not independent (we always chain from the current tip); the real check is the end-of-run verify.

_Report generated by `scripts/layer1_e2e_test.py`_
"""

    filepath.write_text(report, encoding="utf-8")
    print(f"\n✅  Report written to {filepath}")
    return filepath


async def run_test(*, symbols: list[str], duration_s: int, output_dir: Path) -> Path:
    sources: list[ExchangeId] = ["binance", "coinbase", "kraken", "okx", "bybit"]
    m = Metrics(sources=[str(s) for s in sources], symbols=symbols)

    consensus_cfg = ConsensusConfig(
        divergence_tolerance=0.003,
        aggregation_window_ms=50,
        escalate_after=3,
        min_sources_for_consensus=2,
    )
    consensus = ConsensusEngine(consensus_cfg)
    aligner = TickAligner(window_ms=consensus_cfg.aggregation_window_ms)
    weights: TrustWeights = load_trust_weights()

    output_dir.mkdir(parents=True, exist_ok=True)
    hash_path = output_dir / "layer1_e2e_hash_chain.jsonl"
    if hash_path.exists():
        hash_path.unlink()

    hashlog = HashChainLogger(path=hash_path)
    hashlog.start()

    def liveness_audit(event_type: str, payload: dict) -> None:
        emit_audit_event(event_type, source="layer1_e2e_test", payload=payload)
        if event_type == "exchange_silent":
            m.liveness_alerts.append(
                {
                    "source": payload.get("source"),
                    "silence_ms": float(payload.get("silence_ms", 0.0)),
                    "elapsed_s": time.time() - m.start_time,
                }
            )
        if event_type == "exchange_recovered":
            m.liveness_recoveries.append(
                {
                    "source": payload.get("source"),
                    "silent_ms": float(payload.get("silent_ms", 0.0)),
                    "elapsed_s": time.time() - m.start_time,
                }
            )

    liveness = ExchangeLivenessMonitor(sources=[str(s) for s in sources], audit_fn=liveness_audit)

    adapters = {
        "binance": BinanceAdapter(symbols),
        "coinbase": CoinbaseAdapter(symbols),
        "kraken": KrakenAdapter(symbols),
        "okx": OkxAdapter(symbols),
        "bybit": BybitAdapter(symbols),
    }

    tick_queue: asyncio.Queue[NormalizedTick] = asyncio.Queue(maxsize=50_000)

    async def adapter_task(name: str, adapter) -> None:
        async for tick in adapter.run_forever():
            m.record_tick(name, tick)
            liveness.record_tick(name)
            try:
                tick_queue.put_nowait(tick)
            except asyncio.QueueFull:
                m.tick_dropped += 1

    async def pipeline_task() -> None:
        last_liveness_check = 0.0
        deadline = time.time() + duration_s

        while time.time() < deadline:
            try:
                tick = await asyncio.wait_for(tick_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                now_s = time.time()
                if now_s - last_liveness_check >= 1.0:
                    liveness.check_all()
                    last_liveness_check = now_s
                continue

            now_s = time.time()
            if now_s - last_liveness_check >= 1.0:
                liveness.check_all()
                last_liveness_check = now_s

            for window in aligner.add(tick):
                m.record_alignment(window)

                out = consensus.process_aligned(window.symbol, window.by_ex)
                m.record_consensus(out, min_sources_for_consensus=consensus_cfg.min_sources_for_consensus)
                if out.consensus_mid is None:
                    continue

                primary_tick = window.by_ex.get(PRIMARY_EXCHANGE)
                if primary_tick is None or PRIMARY_EXCHANGE not in out.used_sources:
                    continue

                usable_ticks = [primary_tick]

                tolerance = abs(float(out.consensus_mid)) * float(consensus.config.divergence_tolerance)
                t2 = compute_t2(
                    ticks_with_age=window.ticks_with_age,
                    consensus_price=float(out.consensus_mid),
                    tolerance=tolerance,
                    active_sources=window.active_sources,
                )

                latency_ms = _median_latency_ms(usable_ticks, now_ms=window.window_end_ms)
                spread = _median_spread(usable_ticks)
                volume_24h = _median_volume_24h(usable_ticks)

                # Mirrors services/layer1_validated/service.py assumptions for Phase 2.
                subscores = compute_subscores(
                    tls_ok=True,
                    t2=t2,
                    latency_ms=latency_ms,
                    sequence_gap=None,
                    chain_ok=True,
                )
                trust = compute_trust_score(weights=weights, subscores=subscores)
                m.record_trust(
                    subscores=subscores,
                    trust=trust,
                    latency_ms=latency_ms,
                    spread=spread,
                    volume_24h=volume_24h,
                )

                try:
                    prev = hashlog.tip
                    _tick_hash, chain_ok = hashlog.append(
                        symbol=window.symbol,
                        primary_exchange=PRIMARY_EXCHANGE,
                        primary_mid_price=float(primary_tick.mid),
                        consensus_mid=float(out.consensus_mid),
                        used_sources=out.used_sources,
                        divergent_sources=out.divergent_sources,
                        trust_score=float(trust),
                        received_timestamp_ms=int(window.window_end_ms),
                        previous_hash=prev,
                    )
                    m.hashchain_appends += 1
                    if not chain_ok:
                        m.hashchain_errors += 1
                except Exception:
                    m.hashchain_errors += 1

    tasks = [asyncio.create_task(adapter_task(name, adapter), name=f"adapter:{name}") for name, adapter in adapters.items()]
    pipeline = asyncio.create_task(pipeline_task(), name="pipeline")

    print(f"⏱  Running {duration_s}s soak across {len(sources)} sources…")

    try:
        await pipeline
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for adapter in adapters.values():
            await adapter.close()
        hashlog.stop()

    ok, msg = verify_hash_chain(hash_path)
    return generate_report(
        m=m,
        duration_s=duration_s,
        output_dir=output_dir,
        hashchain_ok=ok,
        hashchain_msg=msg,
        hash_path=hash_path,
        consensus_cfg=consensus_cfg,
        weights=weights,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Layer 1 E2E test")
    parser.add_argument("--symbols", default="BTC-USDT", help="Comma-separated symbols")
    parser.add_argument("--duration", type=int, default=1200, help="Test duration in seconds (default 1200 = 20 min)")
    parser.add_argument("--output", default="artifacts/reports/", help="Output directory for the report")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    output_dir = Path(args.output)
    asyncio.run(run_test(symbols=symbols, duration_s=int(args.duration), output_dir=output_dir))


if __name__ == "__main__":
    main()
