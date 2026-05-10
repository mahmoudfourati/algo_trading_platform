"""Tests for Layer 3 dual-timeframe signal logic."""

from __future__ import annotations

from services.layer3_strategy.indicators import IndicatorSnapshot
from services.layer3_strategy.ofi import OrderFlowImbalanceSnapshot
from services.layer3_strategy.signals import evaluate_dual_timeframe_signal


def _indicator_snapshot(
    *,
    symbol: str = "BTC-USDT",
    timeframe: str,
    close: float,
    rsi: float | None,
    macd_histogram: float | None,
    bollinger_middle: float | None,
    bollinger_upper: float | None,
    bollinger_lower: float | None,
    ema_fast: float | None,
    ema_slow: float | None,
    ema_alignment: str | None = None,
    ema_cross: str | None = None,
    adx: float | None = None,
    regime: str | None = None,
    candle_reliable: bool = True,
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        candle_start_time_utc=0,
        candle_end_time_utc=300_000 if timeframe == "5m" else 3_600_000,
        close=close,
        rsi=rsi,
        macd=macd_histogram,
        macd_signal=macd_histogram,
        macd_histogram=macd_histogram,
        bollinger_middle=bollinger_middle,
        bollinger_upper=bollinger_upper,
        bollinger_lower=bollinger_lower,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        ema_alignment=ema_alignment,
        ema_cross=ema_cross,
        atr=1.0,
        adx=adx,
        regime=regime,
        candle_reliable=candle_reliable,
    )


def _ofi_snapshot(*, ofi: float) -> OrderFlowImbalanceSnapshot:
    return OrderFlowImbalanceSnapshot(
        symbol="BTC-USDT",
        timestamp_utc=1_700_000_000_000,
        mid_price=100.0,
        ofi=ofi,
        buy_volume=max(ofi, 0.0),
        sell_volume=max(-ofi, 0.0),
        tick_count=50,
        window_size=50,
    )


def test_long_signal_passes_all_gates_with_full_confluence() -> None:
    primary = [
        _indicator_snapshot(timeframe="5m", close=100.5, rsi=40.0, macd_histogram=0.01, bollinger_middle=101.0, bollinger_upper=102.0, bollinger_lower=100.0, ema_fast=99.5, ema_slow=100.0, ema_alignment="bearish"),
        _indicator_snapshot(timeframe="5m", close=100.2, rsi=35.0, macd_histogram=0.015, bollinger_middle=100.8, bollinger_upper=101.8, bollinger_lower=100.0, ema_fast=99.8, ema_slow=100.1, ema_alignment="bullish", ema_cross="bullish"),
        _indicator_snapshot(timeframe="5m", close=99.4, rsi=30.0, macd_histogram=0.02, bollinger_middle=100.6, bollinger_upper=101.6, bollinger_lower=100.0, ema_fast=100.2, ema_slow=99.9, ema_alignment="bullish"),
    ]
    higher = [
        _indicator_snapshot(timeframe="1h", close=100.8, rsi=57.0, macd_histogram=-0.02, bollinger_middle=101.5, bollinger_upper=103.0, bollinger_lower=99.0, ema_fast=100.0, ema_slow=100.5),
        _indicator_snapshot(timeframe="1h", close=100.2, rsi=50.0, macd_histogram=0.01, bollinger_middle=101.2, bollinger_upper=102.8, bollinger_lower=99.5, ema_fast=100.4, ema_slow=100.2),
    ]

    signal = evaluate_dual_timeframe_signal(
        symbol="BTC-USDT",
        primary_snapshots=primary,
        higher_snapshots=higher,
        ofi_snapshot=_ofi_snapshot(ofi=0.25),
        system_state="NORMAL",
    )

    assert signal.direction == "LONG"
    assert signal.confluence == "FULL"
    assert signal.signal_strength > 0.0
    assert signal.size_pct == 0.0


def test_short_signal_passes_symmetrical_gates() -> None:
    primary = [
        _indicator_snapshot(timeframe="5m", close=100.0, rsi=60.0, macd_histogram=-0.01, bollinger_middle=100.5, bollinger_upper=101.0, bollinger_lower=99.0, ema_fast=100.5, ema_slow=100.0, ema_alignment="bullish"),
        _indicator_snapshot(timeframe="5m", close=100.8, rsi=66.0, macd_histogram=-0.015, bollinger_middle=100.7, bollinger_upper=101.0, bollinger_lower=99.2, ema_fast=100.2, ema_slow=100.4, ema_alignment="bearish", ema_cross="bearish"),
        _indicator_snapshot(timeframe="5m", close=101.2, rsi=70.0, macd_histogram=-0.02, bollinger_middle=100.9, bollinger_upper=101.0, bollinger_lower=99.5, ema_fast=100.0, ema_slow=100.6, ema_alignment="bearish"),
    ]
    higher = [
        _indicator_snapshot(timeframe="1h", close=100.5, rsi=44.0, macd_histogram=0.01, bollinger_middle=100.0, bollinger_upper=101.0, bollinger_lower=99.0, ema_fast=100.0, ema_slow=100.1),
        _indicator_snapshot(timeframe="1h", close=100.8, rsi=56.0, macd_histogram=-0.01, bollinger_middle=101.0, bollinger_upper=102.0, bollinger_lower=100.0, ema_fast=99.9, ema_slow=100.2),
    ]

    signal = evaluate_dual_timeframe_signal(
        symbol="BTC-USDT",
        primary_snapshots=primary,
        higher_snapshots=higher,
        ofi_snapshot=_ofi_snapshot(ofi=-0.22),
        system_state="CONSERVATIVE",
    )

    assert signal.direction == "SHORT"
    assert signal.confluence == "PARTIAL"
    assert signal.signal_strength > 0.0


def test_ofi_gate_blocks_when_confirmation_is_missing() -> None:
    primary = [
        _indicator_snapshot(timeframe="5m", close=100.5, rsi=40.0, macd_histogram=0.01, bollinger_middle=101.0, bollinger_upper=102.0, bollinger_lower=100.0, ema_fast=99.5, ema_slow=100.0),
        _indicator_snapshot(timeframe="5m", close=100.2, rsi=35.0, macd_histogram=0.015, bollinger_middle=100.8, bollinger_upper=101.8, bollinger_lower=100.0, ema_fast=99.8, ema_slow=100.1, ema_cross="bullish"),
        _indicator_snapshot(timeframe="5m", close=99.4, rsi=30.0, macd_histogram=0.02, bollinger_middle=100.6, bollinger_upper=101.6, bollinger_lower=100.0, ema_fast=100.2, ema_slow=99.9),
    ]
    higher = [
        _indicator_snapshot(timeframe="1h", close=100.8, rsi=57.0, macd_histogram=-0.02, bollinger_middle=101.5, bollinger_upper=103.0, bollinger_lower=99.0, ema_fast=100.0, ema_slow=100.5),
        _indicator_snapshot(timeframe="1h", close=100.2, rsi=50.0, macd_histogram=0.01, bollinger_middle=101.2, bollinger_upper=102.8, bollinger_lower=99.5, ema_fast=100.4, ema_slow=100.2),
    ]

    signal = evaluate_dual_timeframe_signal(
        symbol="BTC-USDT",
        primary_snapshots=primary,
        higher_snapshots=higher,
        ofi_snapshot=_ofi_snapshot(ofi=0.05),
        system_state="NORMAL",
    )

    assert signal.direction == "HOLD"
    assert signal.confluence == "NONE"


def test_higher_timeframe_disagreement_blocks_signal() -> None:
    primary = [
        _indicator_snapshot(timeframe="5m", close=100.5, rsi=40.0, macd_histogram=0.01, bollinger_middle=101.0, bollinger_upper=102.0, bollinger_lower=100.0, ema_fast=99.5, ema_slow=100.0),
        _indicator_snapshot(timeframe="5m", close=100.2, rsi=35.0, macd_histogram=0.015, bollinger_middle=100.8, bollinger_upper=101.8, bollinger_lower=100.0, ema_fast=99.8, ema_slow=100.1, ema_cross="bullish"),
        _indicator_snapshot(timeframe="5m", close=99.4, rsi=30.0, macd_histogram=0.02, bollinger_middle=100.6, bollinger_upper=101.6, bollinger_lower=100.0, ema_fast=100.2, ema_slow=99.9),
    ]
    higher = [
        _indicator_snapshot(timeframe="1h", close=101.8, rsi=60.0, macd_histogram=-0.02, bollinger_middle=101.0, bollinger_upper=102.0, bollinger_lower=99.5, ema_fast=100.0, ema_slow=100.5),
        _indicator_snapshot(timeframe="1h", close=101.6, rsi=58.0, macd_histogram=-0.01, bollinger_middle=101.1, bollinger_upper=102.0, bollinger_lower=99.8, ema_fast=100.1, ema_slow=100.4),
    ]

    signal = evaluate_dual_timeframe_signal(
        symbol="BTC-USDT",
        primary_snapshots=primary,
        higher_snapshots=higher,
        ofi_snapshot=_ofi_snapshot(ofi=0.22),
        system_state="NORMAL",
    )

    assert signal.direction == "HOLD"
    assert signal.confluence == "NONE"


def test_system_state_gate_blocks_degraded_and_halt() -> None:
    primary = [
        _indicator_snapshot(timeframe="5m", close=99.4, rsi=30.0, macd_histogram=0.02, bollinger_middle=100.6, bollinger_upper=101.6, bollinger_lower=100.0, ema_fast=100.2, ema_slow=99.9, ema_cross="bullish"),
        _indicator_snapshot(timeframe="5m", close=99.2, rsi=29.0, macd_histogram=0.03, bollinger_middle=100.4, bollinger_upper=101.4, bollinger_lower=100.0, ema_fast=100.3, ema_slow=99.8),
        _indicator_snapshot(timeframe="5m", close=99.0, rsi=28.0, macd_histogram=0.04, bollinger_middle=100.3, bollinger_upper=101.3, bollinger_lower=100.0, ema_fast=100.4, ema_slow=99.7),
    ]
    higher = [
        _indicator_snapshot(timeframe="1h", close=100.2, rsi=50.0, macd_histogram=0.01, bollinger_middle=101.2, bollinger_upper=102.8, bollinger_lower=99.5, ema_fast=100.4, ema_slow=100.2),
        _indicator_snapshot(timeframe="1h", close=100.0, rsi=49.0, macd_histogram=0.02, bollinger_middle=101.0, bollinger_upper=102.5, bollinger_lower=99.4, ema_fast=100.5, ema_slow=100.1),
    ]

    degraded_signal = evaluate_dual_timeframe_signal(
        symbol="BTC-USDT",
        primary_snapshots=primary,
        higher_snapshots=higher,
        ofi_snapshot=_ofi_snapshot(ofi=0.2),
        system_state="DEGRADED",
    )
    halt_signal = evaluate_dual_timeframe_signal(
        symbol="BTC-USDT",
        primary_snapshots=primary,
        higher_snapshots=higher,
        ofi_snapshot=_ofi_snapshot(ofi=0.2),
        system_state="HALT",
    )

    assert degraded_signal.direction == "HOLD"
    assert halt_signal.direction == "HOLD"
    assert degraded_signal.confluence == "NONE"
    assert halt_signal.confluence == "NONE"