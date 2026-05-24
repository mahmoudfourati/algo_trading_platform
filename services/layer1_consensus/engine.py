"""Layer 1 tick alignment and consensus.

Aligns ticks into short windows and applies divergence/quarantine rules to compute consensus.
"""

from __future__ import annotations

import dataclasses
import time
from collections import defaultdict
from typing import DefaultDict, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from shared.audit import emit_audit_event
from shared.schemas import ExchangeId, NormalizedTick

if TYPE_CHECKING:
    from .window_config import ConsensusWindowConfig


LKV_STALENESS_MS = 15_000
LIVENESS_THRESHOLD_MS = 30_000


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
            used_sources = sorted({t.exchange_id for t in usable})
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
    """Align ticks per-symbol into configurable aggregation windows.
    
    Supports per-symbol window configuration for different trading strategies.
    """

    def __init__(
        self,
        *,
        window_ms: int = 50,
        window_config: Optional["ConsensusWindowConfig"] = None,
    ) -> None:
        """Initialize TickAligner.
        
        Args:
            window_ms: Default window size in milliseconds (used if window_config not provided)
            window_config: Optional per-symbol window configuration
        """
        self.default_window_ms = int(window_ms)
        self.window_config = window_config
        self._buf: DefaultDict[str, List[NormalizedTick]] = defaultdict(list)
        self._window_start_ms: Dict[str, int] = {}

        # Per-symbol last-known-value registry (exchange -> latest tick) + last-seen timestamps.
        self._lkv: DefaultDict[str, Dict[ExchangeId, NormalizedTick]] = defaultdict(dict)
        self._lkv_ts: DefaultDict[str, Dict[ExchangeId, float]] = defaultdict(dict)
    
    def get_window_ms(self, symbol: str) -> int:
        """Get alignment window for a symbol.
        
        Args:
            symbol: Symbol name (e.g., "BTC-USDT")
            
        Returns:
            Window size in milliseconds
        """
        if self.window_config is not None:
            return self.window_config.get_window_ms(symbol)
        return self.default_window_ms

    def add(self, tick: NormalizedTick) -> List["AlignedWindow"]:
        symbol = tick.symbol
        self._buf[symbol].append(tick)
        if symbol not in self._window_start_ms:
            self._window_start_ms[symbol] = tick.received_timestamp_ms

        # Always update LKV for this symbol/source.
        self._lkv[symbol][tick.exchange_id] = tick
        self._lkv_ts[symbol][tick.exchange_id] = float(tick.received_timestamp_ms)

        return self.flush_due(now_ms=tick.received_timestamp_ms)

    def active_sources(self, *, symbol: str, now_ms: float) -> set[ExchangeId]:
        """Sources for this symbol seen within LIVENESS_THRESHOLD_MS."""

        return {
            s
            for s, ts in self._lkv_ts.get(symbol, {}).items()
            if now_ms - float(ts) <= float(LIVENESS_THRESHOLD_MS)
        }

    def flush_due(self, *, now_ms: int) -> List["AlignedWindow"]:
        now_f = float(now_ms)
        ready: List[AlignedWindow] = []

        for symbol in list(self._buf.keys()):
            start = self._window_start_ms.get(symbol)
            if start is None:
                continue
            
            # Use per-symbol window size
            window_ms = self.get_window_ms(symbol)
            if now_ms - start < window_ms:
                continue

            ticks = self._buf.pop(symbol, [])
            self._window_start_ms.pop(symbol, None)

            window_ticks: Dict[ExchangeId, NormalizedTick] = {}
            for t in ticks:
                # Keep the last tick per exchange within the window.
                window_ticks[t.exchange_id] = t

            # Fill missing sources from LKV, subject to staleness gating.
            ticks_with_age: List[Tuple[NormalizedTick, float]] = []
            merged: Dict[ExchangeId, NormalizedTick] = dict(window_ticks)

            for ex, t in window_ticks.items():
                ticks_with_age.append((t, 0.0))

            all_sources = set(self._lkv.get(symbol, {}).keys())
            for ex in all_sources:
                if ex in window_ticks:
                    continue
                lkv_tick = self._lkv.get(symbol, {}).get(ex)
                lkv_ts = float(self._lkv_ts.get(symbol, {}).get(ex, 0.0))
                age_ms = now_f - lkv_ts
                if lkv_tick is not None and age_ms <= float(LKV_STALENESS_MS):
                    merged[ex] = lkv_tick
                    ticks_with_age.append((lkv_tick, age_ms))

            active = self.active_sources(symbol=symbol, now_ms=now_f)

            ready.append(
                AlignedWindow(
                    symbol=symbol,
                    window_end_ms=int(now_ms),
                    by_ex=merged,
                    ticks_with_age=ticks_with_age,
                    active_sources=active,
                )
            )

        return ready


@dataclasses.dataclass(frozen=True)
class AlignedWindow:
    """One aligned aggregation window for a symbol.

    Includes LKV-filled ticks and their age (ms) for weighted trust scoring.
    """

    symbol: str
    window_end_ms: int
    by_ex: Dict[ExchangeId, NormalizedTick]
    ticks_with_age: List[Tuple[NormalizedTick, float]]
    active_sources: set[ExchangeId]
