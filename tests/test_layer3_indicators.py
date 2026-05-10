"""Tests for Layer 3 indicator calculations."""

from __future__ import annotations

import importlib.util
from math import isclose
from statistics import mean, pstdev

from services.layer3_strategy.candles import Candle
from services.layer3_strategy.indicators import IndicatorManager, TimeframeIndicatorState


TA_LIB_AVAILABLE = importlib.util.find_spec("talib") is not None


def _build_candle(index: int, close: float, *, timeframe: str = "5m", reliable: bool = True) -> Candle:
    return Candle(
        symbol="BTC-USDT",
        timeframe=timeframe,
        start_time_utc=index * 300_000,
        end_time_utc=(index + 1) * 300_000,
        open=close - 0.5,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=100.0,
        tick_count=10,
        avg_trust_score=0.9,
        max_anomaly_score=0.1,
        is_reliable=reliable,
        consecutive_unreliable_candles=0,
        discarded=False,
    )


def _ema_series(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return [None] * len(values)
    outputs: list[float | None] = [None] * len(values)
    ema_value = mean(values[:period])
    outputs[period - 1] = ema_value
    smoothing = 2.0 / (period + 1.0)
    for index in range(period, len(values)):
        ema_value = (values[index] - ema_value) * smoothing + ema_value
        outputs[index] = ema_value
    return outputs


def _rsi_series(values: list[float], period: int = 14) -> list[float | None]:
    outputs: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return outputs

    gains = []
    losses = []
    for index in range(1, period + 1):
        delta = values[index] - values[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    average_gain = mean(gains)
    average_loss = mean(losses)

    def _calc(gain: float, loss: float) -> float:
        if isclose(loss, 0.0):
            return 100.0 if not isclose(gain, 0.0) else 50.0
        return 100.0 - (100.0 / (1.0 + gain / loss))

    outputs[period] = _calc(average_gain, average_loss)
    for index in range(period + 1, len(values)):
        delta = values[index] - values[index - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
        outputs[index] = _calc(average_gain, average_loss)
    return outputs


def _bollinger_series(values: list[float], period: int = 20, multiplier: float = 2.0) -> tuple[list[float | None], list[float | None], list[float | None]]:
    middle: list[float | None] = [None] * len(values)
    upper: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index + 1 - period : index + 1]
        center = mean(window)
        deviation = pstdev(window)
        middle[index] = center
        upper[index] = center + (multiplier * deviation)
        lower[index] = center - (multiplier * deviation)
    return middle, upper, lower


def _atr_series(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    true_ranges: list[float] = []
    for index, (high, low) in enumerate(zip(highs, lows, strict=True)):
        previous_close = closes[index - 1] if index > 0 else None
        if previous_close is None:
            true_ranges.append(high - low)
        else:
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))

    outputs: list[float | None] = [None] * len(true_ranges)
    if len(true_ranges) < period:
        return outputs

    atr_value = mean(true_ranges[:period])
    outputs[period - 1] = atr_value
    for index in range(period, len(true_ranges)):
        atr_value = ((atr_value * (period - 1)) + true_ranges[index]) / period
        outputs[index] = atr_value
    return outputs


def _macd_series(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float | None], list[float | None], list[float | None]]:
    fast_ema = _ema_series(values, fast)
    slow_ema = _ema_series(values, slow)
    macd_line: list[float | None] = [None] * len(values)
    compact: list[float] = []
    compact_indexes: list[int] = []

    for index, (fast_value, slow_value) in enumerate(zip(fast_ema, slow_ema, strict=True)):
        if fast_value is None or slow_value is None:
            continue
        macd_value = fast_value - slow_value
        macd_line[index] = macd_value
        compact.append(macd_value)
        compact_indexes.append(index)

    signal_line: list[float | None] = [None] * len(values)
    histogram: list[float | None] = [None] * len(values)
    signal_ema = _ema_series(compact, signal)
    for compact_index, source_index in enumerate(compact_indexes):
        signal_value = signal_ema[compact_index]
        if signal_value is None:
            continue
        signal_line[source_index] = signal_value
        histogram[source_index] = macd_line[source_index] - signal_value
    return macd_line, signal_line, histogram


def test_indicators_match_independent_reference_calculations() -> None:
    closes = [100.0, 101.0, 102.0, 101.0, 103.0, 104.0, 103.0, 105.0, 106.0, 108.0, 107.0, 109.0, 110.0, 111.0, 112.0, 111.0, 113.0, 114.0, 115.0, 116.0, 115.0, 117.0, 118.0, 119.0, 120.0, 121.0, 122.0, 121.0, 123.0, 124.0, 125.0, 126.0, 127.0, 128.0, 129.0]
    candles = [_build_candle(index, close) for index, close in enumerate(closes)]

    state = TimeframeIndicatorState(symbol="BTC-USDT", timeframe="5m")
    snapshots = [state.process(candle) for candle in candles]
    latest = snapshots[-1]
    assert latest is not None

    rsi_reference = _rsi_series(closes)
    macd_reference, signal_reference, histogram_reference = _macd_series(closes)
    bollinger_middle, bollinger_upper, bollinger_lower = _bollinger_series(closes)
    ema_fast_reference = _ema_series(closes, 9)
    ema_slow_reference = _ema_series(closes, 21)
    atr_reference = _atr_series([close + 1.0 for close in closes], [close - 1.0 for close in closes], closes)

    assert isclose(latest.close, closes[-1])
    assert isclose(latest.rsi, rsi_reference[-1], rel_tol=1e-9, abs_tol=1e-9)
    assert isclose(latest.macd, macd_reference[-1], rel_tol=1e-9, abs_tol=1e-9)
    assert isclose(latest.macd_signal, signal_reference[-1], rel_tol=1e-9, abs_tol=1e-9)
    assert isclose(latest.macd_histogram, histogram_reference[-1], rel_tol=1e-9, abs_tol=1e-9)
    assert isclose(latest.bollinger_middle, bollinger_middle[-1], rel_tol=1e-9, abs_tol=1e-9)
    assert isclose(latest.bollinger_upper, bollinger_upper[-1], rel_tol=1e-9, abs_tol=1e-9)
    assert isclose(latest.bollinger_lower, bollinger_lower[-1], rel_tol=1e-9, abs_tol=1e-9)
    assert isclose(latest.ema_fast, ema_fast_reference[-1], rel_tol=1e-9, abs_tol=1e-9)
    assert isclose(latest.ema_slow, ema_slow_reference[-1], rel_tol=1e-9, abs_tol=1e-9)
    assert isclose(latest.atr, atr_reference[-1], rel_tol=1e-9, abs_tol=1e-9)

    if TA_LIB_AVAILABLE:
        import talib

        talib_rsi = talib.RSI(closes, timeperiod=14)
        talib_macd, talib_macd_signal, talib_macd_hist = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
        talib_upper, talib_middle, talib_lower = talib.BBANDS(closes, timeperiod=20, nbdevup=2.0, nbdevdn=2.0, matype=0)
        talib_ema_fast = talib.EMA(closes, timeperiod=12)
        talib_ema_slow = talib.EMA(closes, timeperiod=26)
        talib_atr = talib.ATR([close + 1.0 for close in closes], [close - 1.0 for close in closes], closes, timeperiod=14)

        assert isclose(latest.rsi, talib_rsi[-1], rel_tol=1e-9, abs_tol=1e-9)
        assert isclose(latest.macd, talib_macd[-1], rel_tol=1e-9, abs_tol=1e-9)
        assert isclose(latest.macd_signal, talib_macd_signal[-1], rel_tol=1e-9, abs_tol=1e-9)
        assert isclose(latest.macd_histogram, talib_macd_hist[-1], rel_tol=1e-9, abs_tol=1e-9)
        assert isclose(latest.bollinger_middle, talib_middle[-1], rel_tol=1e-9, abs_tol=1e-9)
        assert isclose(latest.bollinger_upper, talib_upper[-1], rel_tol=1e-9, abs_tol=1e-9)
        assert isclose(latest.bollinger_lower, talib_lower[-1], rel_tol=1e-9, abs_tol=1e-9)
        assert isclose(latest.ema_fast, talib_ema_fast[-1], rel_tol=1e-9, abs_tol=1e-9)
        assert isclose(latest.ema_slow, talib_ema_slow[-1], rel_tol=1e-9, abs_tol=1e-9)
        assert isclose(latest.atr, talib_atr[-1], rel_tol=1e-9, abs_tol=1e-9)


def test_indicators_respect_warmup_and_cross_detection() -> None:
    candles = [_build_candle(index, float(100 + index)) for index in range(30)]
    state = TimeframeIndicatorState(symbol="BTC-USDT", timeframe="5m")

    snapshots = [state.process(candle) for candle in candles]

    assert snapshots[0] is not None
    assert snapshots[0].rsi is None
    assert snapshots[0].macd is None
    assert snapshots[0].bollinger_middle is None
    assert snapshots[0].atr is None

    assert snapshots[13] is not None
    assert snapshots[13].atr is not None

    assert snapshots[14] is not None
    assert snapshots[14].rsi is not None

    assert snapshots[19] is not None
    assert snapshots[19].bollinger_middle is not None

    assert snapshots[25] is not None
    assert snapshots[25].macd is not None
    assert snapshots[25].macd_signal is None

    assert snapshots[-1] is not None
    assert snapshots[-1].ema_alignment in {"bullish", "bearish", "neutral"}


def test_indicator_manager_keeps_timeframes_independent() -> None:
    manager = IndicatorManager(symbol="BTC-USDT")

    five_minute_candles = [_build_candle(index, 100.0 + index, timeframe="5m") for index in range(4)]
    one_hour_candles = [_build_candle(index, 200.0 + (index * 2.0), timeframe="1h") for index in range(4)]

    for candle in five_minute_candles:
        manager.process(candle)
    for candle in one_hour_candles:
        manager.process(candle)

    five_minute_latest = manager.latest("5m")
    one_hour_latest = manager.latest("1h")

    assert five_minute_latest is not None
    assert one_hour_latest is not None
    assert five_minute_latest.timeframe == "5m"
    assert one_hour_latest.timeframe == "1h"
    assert not isclose(five_minute_latest.close, one_hour_latest.close)
