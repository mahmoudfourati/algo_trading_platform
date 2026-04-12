from __future__ import annotations

import dataclasses
import time
from collections import defaultdict
from typing import DefaultDict, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from shared.audit import emit_audit_event
from shared.schemas import ExchangeId, NormalizedTick


class ConsensusConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    divergence_tolerance: float = Field(default=0.003, description="0.3% divergence tolerance")
    aggregation_window_ms: int = Field(default=50, description="Align ticks within this window")
    escalate_after: int = Field(default=3, description="Consecutive divergences to escalate")
    min_sources_for_consensus: int = Field(default=2, description="Minimum non-quarantined sources")


class ConsensusOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    timestamp_ms: int
    consensus_mid: Optional[float]
    used_sources: List[ExchangeId]
    divergent_sources: List[ExchangeId]
    quarantined_sources: List[ExchangeId]
    escalated_sources: List[ExchangeId]


def _unweighted_median(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("median of empty list")
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def volume_weighted_median(ticks: Sequence[NormalizedTick]) -> float:
    """Compute volume-weighted median of mid prices.

    If weights are all non-positive, falls back to an unweighted median.
    """

    if not ticks:
        raise ValueError("weighted median requires at least one tick")

    items: List[Tuple[float, float]] = []
    for t in ticks:
        w = float(t.volume_24h)
        items.append((t.mid, max(w, 0.0)))

    total_w = sum(w for _, w in items)
    if total_w <= 0:
        return _unweighted_median([m for m, _ in items])

    items.sort(key=lambda x: x[0])
    cumulative = 0.0
    half = total_w / 2.0
    for mid, w in items:
        cumulative += w
        if cumulative >= half:
            return mid

    # Numerical fallback.
    return items[-1][0]


@dataclasses.dataclass
class _SymbolState:
    quarantined: Dict[ExchangeId, NormalizedTick] = dataclasses.field(default_factory=dict)
    divergence_streak: DefaultDict[ExchangeId, int] = dataclasses.field(
        default_factory=lambda: defaultdict(int)
    )


class ConsensusEngine:
    def __init__(self, config: Optional[ConsensusConfig] = None) -> None:
        self.config = config or ConsensusConfig()
        self._state: Dict[str, _SymbolState] = {}

    def process_aligned(self, symbol: str, ticks: Mapping[ExchangeId, NormalizedTick]) -> ConsensusOutput:
        """Process an already-aligned set of per-exchange ticks for a symbol."""

        now_ms = int(time.time() * 1000)
        state = self._state.setdefault(symbol, _SymbolState())

        active_ticks: Dict[ExchangeId, NormalizedTick] = {}
        for ex, t in ticks.items():
            if ex in state.quarantined:
                # Keep only the latest quarantined tick (buffer and re-evaluate on the next tick).
                state.quarantined[ex] = t
            else:
                active_ticks[ex] = t

        # Determine the raw median from active, non-quarantined ticks.
        active_mids = [t.mid for t in active_ticks.values()]
        if active_mids:
            raw_median = _unweighted_median(active_mids)
        else:
            # If everything is quarantined, use the median of quarantined mids just to re-evaluate.
            raw_median = _unweighted_median([t.mid for t in state.quarantined.values()])

        divergent: List[ExchangeId] = []
        escalated: List[ExchangeId] = []

        streak_incremented = set()

        # 1) Evaluate new ticks for divergence.
        for ex, t in list(active_ticks.items()):
            if _is_divergent(t.mid, raw_median, self.config.divergence_tolerance):
                divergent.append(ex)
                state.quarantined[ex] = t
                state.divergence_streak[ex] += 1
                streak_incremented.add(ex)
                if state.divergence_streak[ex] == self.config.escalate_after:
                    escalated.append(ex)
                    emit_audit_event(
                        "consensus.divergence.escalated",
                        source="layer1_consensus",
                        payload={"symbol": symbol, "exchange_id": ex, "streak": state.divergence_streak[ex]},
                    )
                # Remove from active set; quarantined ticks are excluded from consensus until released.
                active_ticks.pop(ex, None)

        # 2) Re-evaluate quarantined ticks against the current raw median from non-quarantined sources.
        # If there are no non-quarantined sources, we re-evaluate against the median of quarantined ticks.
        non_quarantined_mids = [t.mid for t in active_ticks.values()]
        recheck_median = (
            _unweighted_median(non_quarantined_mids)
            if non_quarantined_mids
            else _unweighted_median([t.mid for t in state.quarantined.values()])
        )

        for ex, qt in list(state.quarantined.items()):
            if _is_divergent(qt.mid, recheck_median, self.config.divergence_tolerance):
                # Still divergent: advance the consecutive streak (but don't double-count the same window).
                divergent.append(ex)
                if ex not in streak_incremented:
                    state.divergence_streak[ex] += 1
                    if state.divergence_streak[ex] == self.config.escalate_after:
                        escalated.append(ex)
                        emit_audit_event(
                            "consensus.divergence.escalated",
                            source="layer1_consensus",
                            payload={"symbol": symbol, "exchange_id": ex, "streak": state.divergence_streak[ex]},
                        )
                continue

            # Release from quarantine.
            state.quarantined.pop(ex, None)
            state.divergence_streak[ex] = 0
            active_ticks[ex] = qt

        # 3) Compute consensus from non-quarantined sources.
        usable: List[NormalizedTick] = list(active_ticks.values())

        consensus_mid: Optional[float]
        used_sources: List[ExchangeId]
        if len(usable) >= self.config.min_sources_for_consensus:
            consensus_mid = volume_weighted_median(usable)
            used_sources = [t.exchange_id for t in usable]
        elif len(usable) == 1:
            # Degraded: not enough sources for a true consensus.
            consensus_mid = usable[0].mid
            used_sources = [usable[0].exchange_id]
        else:
            consensus_mid = None
            used_sources = []

        return ConsensusOutput(
            symbol=symbol,
            timestamp_ms=now_ms,
            consensus_mid=consensus_mid,
            used_sources=used_sources,
            divergent_sources=sorted(set(divergent)),
            quarantined_sources=sorted(state.quarantined.keys()),
            escalated_sources=sorted(set(escalated)),
        )


def _is_divergent(value: float, median: float, tolerance: float) -> bool:
    if median == 0:
        return False
    return abs(value - median) / abs(median) > tolerance


class TickAligner:
    """Align ticks per-symbol into a small aggregation window (default 50ms)."""

    def __init__(self, *, window_ms: int) -> None:
        self.window_ms = int(window_ms)
        self._buf: DefaultDict[str, List[NormalizedTick]] = defaultdict(list)
        self._window_start_ms: Dict[str, int] = {}

    def add(self, tick: NormalizedTick) -> List[Tuple[str, Dict[ExchangeId, NormalizedTick]]]:
        symbol = tick.symbol
        self._buf[symbol].append(tick)
        if symbol not in self._window_start_ms:
            self._window_start_ms[symbol] = tick.received_timestamp_ms

        return self.flush_due(now_ms=tick.received_timestamp_ms)

    def flush_due(self, *, now_ms: int) -> List[Tuple[str, Dict[ExchangeId, NormalizedTick]]]:
        ready: List[Tuple[str, Dict[ExchangeId, NormalizedTick]]] = []

        for symbol in list(self._buf.keys()):
            start = self._window_start_ms.get(symbol)
            if start is None:
                continue
            if now_ms - start < self.window_ms:
                continue

            ticks = self._buf.pop(symbol, [])
            self._window_start_ms.pop(symbol, None)

            by_ex: Dict[ExchangeId, NormalizedTick] = {}
            for t in ticks:
                # Keep the last tick per exchange within the window.
                by_ex[t.exchange_id] = t
            ready.append((symbol, by_ex))

        return ready
