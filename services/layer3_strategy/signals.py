"""Dual-timeframe strategy signal evaluation for Layer 3.

This module stays pure: it consumes finalized indicator snapshots and an OFI
snapshot and returns a deterministic trade signal decision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional, Sequence

from shared.schemas import SystemState

from .indicators import IndicatorSnapshot
from .ofi import OrderFlowImbalanceSnapshot


SignalDirection = Literal["LONG", "SHORT", "HOLD"]
ConfluenceLevel = Literal["FULL", "PARTIAL", "NONE"]


@dataclass(frozen=True)
class SignalThresholds:
    """Thresholds used by the Layer 3 dual-timeframe decision gate."""

    long_rsi_min: float = 25.0
    long_rsi_max: float = 45.0
    short_rsi_min: float = 55.0
    short_rsi_max: float = 75.0
    bollinger_buffer_pct: float = 0.003
    bollinger_strong_pct: float = 0.01
    ema_cross_window: int = 3
    ema_cross_margin_pct: float = 0.001
    ofi_long_threshold: float = 0.10
    ofi_short_threshold: float = -0.10
    higher_long_rsi_max: float = 55.0
    higher_short_rsi_min: float = 45.0


@dataclass(frozen=True)
class TradeSignal:
    """Pure signal decision emitted by the Layer 3 strategy gate."""

    symbol: str
    direction: SignalDirection
    size_pct: float
    signal_strength: float
    confluence: ConfluenceLevel
    ofi: float
    system_state: SystemState
    timestamp_utc: int = 0
    indicator_snapshots: dict[str, dict[str, object]] = field(default_factory=dict)
    candle_reliability: dict[str, bool] = field(default_factory=dict)
    trust_score: float = 1.0
    reason: str = ""


DEFAULT_THRESHOLDS = SignalThresholds()


def evaluate_dual_timeframe_signal(
    *,
    symbol: str,
    primary_snapshots: Sequence[IndicatorSnapshot],
    higher_snapshots: Sequence[IndicatorSnapshot],
    ofi_snapshot: OrderFlowImbalanceSnapshot,
    trust_score: float = 1.0,
    system_state: SystemState,
    thresholds: SignalThresholds = DEFAULT_THRESHOLDS,
) -> TradeSignal:
    """Evaluate the full Step 1-6 signal flow and return a deterministic result."""

    if ofi_snapshot.symbol != symbol:
        raise ValueError(f"OFI symbol {ofi_snapshot.symbol} does not match signal symbol {symbol}")
    if not primary_snapshots:
        return _hold_signal(symbol=symbol, ofi=ofi_snapshot.ofi, trust_score=trust_score, system_state=system_state, reason="missing primary timeframe snapshot")
    if not higher_snapshots:
        return _hold_signal(symbol=symbol, ofi=ofi_snapshot.ofi, trust_score=trust_score, system_state=system_state, reason="missing higher timeframe snapshot")

    latest_primary = primary_snapshots[-1]
    latest_higher = higher_snapshots[-1]

    if latest_primary.symbol != symbol or latest_higher.symbol != symbol:
        raise ValueError("Signal snapshots must all belong to the same symbol")

    signal_context = {
        "timestamp_utc": max(latest_primary.candle_end_time_utc, latest_higher.candle_end_time_utc),
        "indicator_snapshots": {
            "primary": asdict(latest_primary),
            "higher": asdict(latest_higher),
        },
        "candle_reliability": {
            "primary": latest_primary.candle_reliable,
            "higher": latest_higher.candle_reliable,
        },
    }

    if system_state in {"HALT", "DEGRADED"}:
        return _hold_signal(symbol=symbol, ofi=ofi_snapshot.ofi, trust_score=trust_score, system_state=system_state, reason=f"system_state={system_state}")

    if not latest_primary.candle_reliable:
        return _hold_signal(symbol=symbol, ofi=ofi_snapshot.ofi, trust_score=trust_score, system_state=system_state, reason="primary candle not reliable")

    primary_window = list(primary_snapshots[-thresholds.ema_cross_window :])
    higher_window = list(higher_snapshots[-2:])

    long_primary = _primary_long_gate(latest_primary, primary_window, thresholds)
    short_primary = _primary_short_gate(latest_primary, primary_window, thresholds)

    if long_primary and ofi_snapshot.ofi <= thresholds.ofi_long_threshold:
        return _hold_signal(symbol=symbol, ofi=ofi_snapshot.ofi, trust_score=trust_score, system_state=system_state, reason="OFI long gate failed")
    if short_primary and ofi_snapshot.ofi >= thresholds.ofi_short_threshold:
        return _hold_signal(symbol=symbol, ofi=ofi_snapshot.ofi, trust_score=trust_score, system_state=system_state, reason="OFI short gate failed")

    if long_primary:
        confluence_count = _higher_timeframe_confluence_long(latest_higher, higher_window, thresholds)
        if confluence_count < 2:
            return _hold_signal(symbol=symbol, ofi=ofi_snapshot.ofi, trust_score=trust_score, system_state=system_state, reason="higher timeframe disagreement")
        signal_strength = _signal_strength_long(latest_primary, primary_window, thresholds)
        confluence = "FULL" if confluence_count == 3 else "PARTIAL"
        return TradeSignal(
            symbol=symbol,
            direction="LONG",
            size_pct=0.0,
            signal_strength=signal_strength,
            confluence=confluence,
            ofi=ofi_snapshot.ofi,
            system_state=system_state,
            timestamp_utc=signal_context["timestamp_utc"],
            indicator_snapshots=signal_context["indicator_snapshots"],
            candle_reliability=signal_context["candle_reliability"],
            trust_score=trust_score,
            reason="long signal",
        )

    if short_primary:
        confluence_count = _higher_timeframe_confluence_short(latest_higher, higher_window, thresholds)
        if confluence_count < 2:
            return _hold_signal(symbol=symbol, ofi=ofi_snapshot.ofi, trust_score=trust_score, system_state=system_state, reason="higher timeframe disagreement")
        signal_strength = _signal_strength_short(latest_primary, primary_window, thresholds)
        confluence = "FULL" if confluence_count == 3 else "PARTIAL"
        return TradeSignal(
            symbol=symbol,
            direction="SHORT",
            size_pct=0.0,
            signal_strength=signal_strength,
            confluence=confluence,
            ofi=ofi_snapshot.ofi,
            system_state=system_state,
            timestamp_utc=signal_context["timestamp_utc"],
            indicator_snapshots=signal_context["indicator_snapshots"],
            candle_reliability=signal_context["candle_reliability"],
            trust_score=trust_score,
            reason="short signal",
        )

    return _hold_signal(symbol=symbol, ofi=ofi_snapshot.ofi, trust_score=trust_score, system_state=system_state, reason="primary gate failed")


def _hold_signal(
    *,
    symbol: str,
    ofi: float,
    system_state: SystemState,
    trust_score: float = 1.0,
    reason: str,
    timestamp_utc: int = 0,
    indicator_snapshots: dict[str, dict[str, object]] | None = None,
    candle_reliability: dict[str, bool] | None = None,
) -> TradeSignal:
    return TradeSignal(
        symbol=symbol,
        direction="HOLD",
        size_pct=0.0,
        signal_strength=0.0,
        confluence="NONE",
        ofi=ofi,
        system_state=system_state,
        timestamp_utc=timestamp_utc,
        indicator_snapshots=indicator_snapshots or {},
        candle_reliability=candle_reliability or {},
        trust_score=trust_score,
        reason=reason,
    )


def _primary_long_gate(latest: IndicatorSnapshot, recent: Sequence[IndicatorSnapshot], thresholds: SignalThresholds) -> bool:
    rsi_ok = latest.rsi is not None and thresholds.long_rsi_min <= latest.rsi <= thresholds.long_rsi_max
    macd_ok = _histogram_trending_up(recent, direction="LONG")
    bollinger_ok = latest.bollinger_lower is not None and latest.close <= latest.bollinger_lower * (1.0 + thresholds.bollinger_buffer_pct)
    ema_ok = _ema_alignment_ok(recent, direction="LONG", thresholds=thresholds)
    return rsi_ok and macd_ok and bollinger_ok and ema_ok


def _primary_short_gate(latest: IndicatorSnapshot, recent: Sequence[IndicatorSnapshot], thresholds: SignalThresholds) -> bool:
    rsi_ok = latest.rsi is not None and thresholds.short_rsi_min <= latest.rsi <= thresholds.short_rsi_max
    macd_ok = _histogram_trending_up(recent, direction="SHORT")
    bollinger_ok = latest.bollinger_upper is not None and latest.close >= latest.bollinger_upper * (1.0 - thresholds.bollinger_buffer_pct)
    ema_ok = _ema_alignment_ok(recent, direction="SHORT", thresholds=thresholds)
    return rsi_ok and macd_ok and bollinger_ok and ema_ok


def _histogram_trending_up(recent: Sequence[IndicatorSnapshot], *, direction: str) -> bool:
    latest = recent[-1]
    previous = recent[-2] if len(recent) >= 2 else None
    if latest.macd_histogram is None or previous is None or previous.macd_histogram is None:
        return False
    if direction == "LONG":
        return latest.macd_histogram > 0.0 and latest.macd_histogram > previous.macd_histogram
    return latest.macd_histogram < 0.0 and latest.macd_histogram < previous.macd_histogram


def _ema_alignment_ok(recent: Sequence[IndicatorSnapshot], *, direction: str, thresholds: SignalThresholds) -> bool:
    latest = recent[-1]
    recent_cross = any(snapshot.ema_cross == ("bullish" if direction == "LONG" else "bearish") for snapshot in recent)
    if recent_cross:
        return True

    if latest.ema_fast is None or latest.ema_slow is None or latest.ema_slow == 0.0:
        return False

    distance_pct = abs(latest.ema_fast - latest.ema_slow) / abs(latest.ema_slow)
    return distance_pct <= thresholds.ema_cross_margin_pct


def _higher_timeframe_confluence_long(
    latest: IndicatorSnapshot,
    recent: Sequence[IndicatorSnapshot],
    thresholds: SignalThresholds,
) -> int:
    conditions = [
        latest.rsi is not None and latest.rsi < thresholds.higher_long_rsi_max,
        _higher_timeframe_histogram_turning_long(recent),
        latest.bollinger_middle is not None and latest.close < latest.bollinger_middle,
    ]
    return sum(1 for condition in conditions if condition)


def _higher_timeframe_confluence_short(
    latest: IndicatorSnapshot,
    recent: Sequence[IndicatorSnapshot],
    thresholds: SignalThresholds,
) -> int:
    conditions = [
        latest.rsi is not None and latest.rsi > thresholds.higher_short_rsi_min,
        _higher_timeframe_histogram_turning_short(recent),
        latest.bollinger_middle is not None and latest.close > latest.bollinger_middle,
    ]
    return sum(1 for condition in conditions if condition)


def _higher_timeframe_histogram_turning_long(recent: Sequence[IndicatorSnapshot]) -> bool:
    latest = recent[-1]
    previous = recent[-2] if len(recent) >= 2 else None
    if latest.macd_histogram is None:
        return False
    if latest.macd_histogram > 0.0:
        return True
    return previous is not None and previous.macd_histogram is not None and previous.macd_histogram < 0.0 and latest.macd_histogram >= 0.0


def _higher_timeframe_histogram_turning_short(recent: Sequence[IndicatorSnapshot]) -> bool:
    latest = recent[-1]
    previous = recent[-2] if len(recent) >= 2 else None
    if latest.macd_histogram is None:
        return False
    if latest.macd_histogram < 0.0:
        return True
    return previous is not None and previous.macd_histogram is not None and previous.macd_histogram > 0.0 and latest.macd_histogram <= 0.0


def _signal_strength_long(latest: IndicatorSnapshot, recent: Sequence[IndicatorSnapshot], thresholds: SignalThresholds) -> float:
    rsi_score = _clip01((thresholds.long_rsi_max - latest.rsi) / (thresholds.long_rsi_max - thresholds.long_rsi_min)) if latest.rsi is not None else 0.0
    macd_score = _macd_strength_long(recent)
    bollinger_score = _bollinger_strength_long(latest, thresholds)
    ema_score = _ema_strength(latest, recent, direction="LONG", thresholds=thresholds)
    return _clip01((rsi_score + macd_score + bollinger_score + ema_score) / 4.0)


def _signal_strength_short(latest: IndicatorSnapshot, recent: Sequence[IndicatorSnapshot], thresholds: SignalThresholds) -> float:
    rsi_score = _clip01((latest.rsi - thresholds.short_rsi_min) / (thresholds.short_rsi_max - thresholds.short_rsi_min)) if latest.rsi is not None else 0.0
    macd_score = _macd_strength_short(recent)
    bollinger_score = _bollinger_strength_short(latest, thresholds)
    ema_score = _ema_strength(latest, recent, direction="SHORT", thresholds=thresholds)
    return _clip01((rsi_score + macd_score + bollinger_score + ema_score) / 4.0)


def _macd_strength_long(recent: Sequence[IndicatorSnapshot]) -> float:
    latest = recent[-1]
    previous = recent[-2]
    if latest.macd_histogram is None or previous.macd_histogram is None:
        return 0.0
    if latest.macd_histogram <= 0.0 or latest.macd_histogram <= previous.macd_histogram:
        return 0.0
    denominator = abs(latest.macd_histogram) + abs(previous.macd_histogram)
    return 1.0 if denominator == 0.0 else _clip01((latest.macd_histogram - previous.macd_histogram) / denominator)


def _macd_strength_short(recent: Sequence[IndicatorSnapshot]) -> float:
    latest = recent[-1]
    previous = recent[-2]
    if latest.macd_histogram is None or previous.macd_histogram is None:
        return 0.0
    if latest.macd_histogram >= 0.0 or latest.macd_histogram >= previous.macd_histogram:
        return 0.0
    denominator = abs(latest.macd_histogram) + abs(previous.macd_histogram)
    return 1.0 if denominator == 0.0 else _clip01((previous.macd_histogram - latest.macd_histogram) / denominator)


def _bollinger_strength_long(latest: IndicatorSnapshot, thresholds: SignalThresholds) -> float:
    if latest.bollinger_lower is None or latest.bollinger_lower == 0.0:
        return 0.0
    distance_pct = (latest.bollinger_lower - latest.close) / latest.bollinger_lower
    return _clip01((distance_pct + thresholds.bollinger_buffer_pct) / (thresholds.bollinger_strong_pct + thresholds.bollinger_buffer_pct))


def _bollinger_strength_short(latest: IndicatorSnapshot, thresholds: SignalThresholds) -> float:
    if latest.bollinger_upper is None or latest.bollinger_upper == 0.0:
        return 0.0
    distance_pct = (latest.close - latest.bollinger_upper) / latest.bollinger_upper
    return _clip01((distance_pct + thresholds.bollinger_buffer_pct) / (thresholds.bollinger_strong_pct + thresholds.bollinger_buffer_pct))


def _ema_strength(latest: IndicatorSnapshot, recent: Sequence[IndicatorSnapshot], *, direction: str, thresholds: SignalThresholds) -> float:
    if any(snapshot.ema_cross == ("bullish" if direction == "LONG" else "bearish") for snapshot in recent):
        return 1.0
    if latest.ema_fast is None or latest.ema_slow is None or latest.ema_slow == 0.0:
        return 0.0
    distance_pct = abs(latest.ema_fast - latest.ema_slow) / abs(latest.ema_slow)
    if distance_pct >= thresholds.ema_cross_margin_pct:
        return 0.0
    return _clip01(1.0 - (distance_pct / thresholds.ema_cross_margin_pct))


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))
