"""Layer 3 indicator calculations for timeframe-specific candle streams.

The strategy layer consumes finalized candles and maintains independent
indicator state for the 5m and 1h streams.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from statistics import mean, pstdev
from typing import Iterable, Optional, Sequence

from .candles import Candle


def _ema_series(values: Sequence[float], period: int) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError("EMA period must be positive")

    outputs: list[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return outputs

    ema_value = mean(values[:period])
    outputs[period - 1] = ema_value
    smoothing = 2.0 / (period + 1.0)

    for index in range(period, len(values)):
        ema_value = (values[index] - ema_value) * smoothing + ema_value
        outputs[index] = ema_value

    return outputs


def _rsi_series(values: Sequence[float], period: int) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError("RSI period must be positive")

    outputs: list[Optional[float]] = [None] * len(values)
    if len(values) <= period:
        return outputs

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, period + 1):
        delta = values[index] - values[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    average_gain = mean(gains)
    average_loss = mean(losses)

    def _compute_rsi(current_gain: float, current_loss: float) -> float:
        if isclose(current_loss, 0.0):
            return 100.0 if not isclose(current_gain, 0.0) else 50.0
        relative_strength = current_gain / current_loss
        return 100.0 - (100.0 / (1.0 + relative_strength))

    outputs[period] = _compute_rsi(average_gain, average_loss)

    for index in range(period + 1, len(values)):
        delta = values[index] - values[index - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
        outputs[index] = _compute_rsi(average_gain, average_loss)

    return outputs


def _bollinger_series(values: Sequence[float], period: int, std_dev_multiplier: float) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    if period <= 0:
        raise ValueError("Bollinger period must be positive")

    middle: list[Optional[float]] = [None] * len(values)
    upper: list[Optional[float]] = [None] * len(values)
    lower: list[Optional[float]] = [None] * len(values)

    for index in range(period - 1, len(values)):
        window = values[index + 1 - period : index + 1]
        center = mean(window)
        deviation = pstdev(window)
        middle[index] = center
        upper[index] = center + (std_dev_multiplier * deviation)
        lower[index] = center - (std_dev_multiplier * deviation)

    return middle, upper, lower


def _true_range(high: float, low: float, previous_close: Optional[float]) -> float:
    if previous_close is None:
        return high - low
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def _atr_series(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError("ATR period must be positive")

    true_ranges: list[float] = []
    for index, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True)):
        previous_close = closes[index - 1] if index > 0 else None
        true_ranges.append(_true_range(high, low, previous_close))

    outputs: list[Optional[float]] = [None] * len(true_ranges)
    if len(true_ranges) < period:
        return outputs

    atr_value = mean(true_ranges[:period])
    outputs[period - 1] = atr_value

    for index in range(period, len(true_ranges)):
        atr_value = ((atr_value * (period - 1)) + true_ranges[index]) / period
        outputs[index] = atr_value

    return outputs


def _macd_series(values: Sequence[float], fast_period: int, slow_period: int, signal_period: int) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    if fast_period <= 0 or slow_period <= 0 or signal_period <= 0:
        raise ValueError("MACD periods must be positive")
    if fast_period >= slow_period:
        raise ValueError("MACD fast period must be smaller than slow period")

    fast_ema = _ema_series(values, fast_period)
    slow_ema = _ema_series(values, slow_period)

    macd_line: list[Optional[float]] = [None] * len(values)
    macd_values: list[float] = []
    macd_indexes: list[int] = []

    for index, (fast_value, slow_value) in enumerate(zip(fast_ema, slow_ema, strict=True)):
        if fast_value is None or slow_value is None:
            continue
        macd_value = fast_value - slow_value
        macd_line[index] = macd_value
        macd_values.append(macd_value)
        macd_indexes.append(index)

    signal_line: list[Optional[float]] = [None] * len(values)
    histogram: list[Optional[float]] = [None] * len(values)
    if len(macd_values) < signal_period:
        return macd_line, signal_line, histogram

    signal_values = _ema_series(macd_values, signal_period)
    for compact_index, source_index in enumerate(macd_indexes):
        signal_value = signal_values[compact_index]
        if signal_value is None:
            continue
        signal_line[source_index] = signal_value
        histogram[source_index] = macd_line[source_index] - signal_value

    return macd_line, signal_line, histogram


def _adx_series(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> list[Optional[float]]:
    """Compute Average Directional Index (ADX) for trend strength measurement.
    
    ADX ranges from 0-100 where:
    - 0-25: weak trend
    - 25-50: developing trend
    - 50-75: strong trend
    - 75-100: very strong trend
    """
    if period <= 0:
        raise ValueError("ADX period must be positive")
    
    outputs: list[Optional[float]] = [None] * len(highs)
    if len(highs) < period + 1:
        return outputs
    
    # Calculate Plus DM and Minus DM
    plus_dm_list: list[float] = []
    minus_dm_list: list[float] = []
    tr_list: list[float] = []
    
    for index in range(1, len(highs)):
        high_diff = highs[index] - highs[index - 1]
        low_diff = lows[index - 1] - lows[index]
        
        plus_dm = max(high_diff, 0.0) if high_diff > low_diff else 0.0
        minus_dm = max(low_diff, 0.0) if low_diff > high_diff else 0.0
        
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
        
        previous_close = closes[index - 1]
        tr = _true_range(highs[index], lows[index], previous_close)
        tr_list.append(tr)
    
    if len(tr_list) < period:
        return outputs
    
    # Calculate DI+ and DI-
    plus_di_list: list[float] = []
    minus_di_list: list[float] = []
    di_diff_list: list[float] = []
    
    plus_dm_sum = sum(plus_dm_list[:period])
    minus_dm_sum = sum(minus_dm_list[:period])
    tr_sum = sum(tr_list[:period])
    
    if tr_sum > 0:
        plus_di = 100.0 * plus_dm_sum / tr_sum
        minus_di = 100.0 * minus_dm_sum / tr_sum
    else:
        plus_di = 0.0
        minus_di = 0.0
    
    plus_di_list.append(plus_di)
    minus_di_list.append(minus_di)
    di_diff = abs(plus_di - minus_di)
    di_sum = plus_di + minus_di if (plus_di + minus_di) > 0 else 1.0
    di_diff_list.append(100.0 * di_diff / di_sum if di_sum > 0 else 0.0)
    
    # Continue with smoothed values
    for index in range(period, len(tr_list)):
        plus_dm_sum = ((plus_dm_sum * (period - 1)) + plus_dm_list[index]) / period
        minus_dm_sum = ((minus_dm_sum * (period - 1)) + minus_dm_list[index]) / period
        tr_sum = ((tr_sum * (period - 1)) + tr_list[index]) / period
        
        if tr_sum > 0:
            plus_di = 100.0 * plus_dm_sum / tr_sum
            minus_di = 100.0 * minus_dm_sum / tr_sum
        else:
            plus_di = 0.0
            minus_di = 0.0
        
        plus_di_list.append(plus_di)
        minus_di_list.append(minus_di)
        di_diff = abs(plus_di - minus_di)
        di_sum = plus_di + minus_di if (plus_di + minus_di) > 0 else 1.0
        di_diff_list.append(100.0 * di_diff / di_sum if di_sum > 0 else 0.0)
    
    # Smooth DI diff to get ADX
    if len(di_diff_list) < period:
        return outputs
    
    adx_value = mean(di_diff_list[:period])
    outputs[period + period - 1] = adx_value
    
    for index in range(period, len(di_diff_list)):
        adx_value = ((adx_value * (period - 1)) + di_diff_list[index]) / period
        outputs[index + period] = adx_value
    
    return outputs


@dataclass(frozen=True)
class IndicatorSnapshot:
    """Computed indicator values for one finalized candle."""

    symbol: str
    timeframe: str
    candle_start_time_utc: int
    candle_end_time_utc: int
    close: float
    rsi: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_histogram: Optional[float]
    bollinger_middle: Optional[float]
    bollinger_upper: Optional[float]
    bollinger_lower: Optional[float]
    ema_fast: Optional[float]
    ema_slow: Optional[float]
    ema_alignment: Optional[str]
    ema_cross: Optional[str]
    atr: Optional[float]
    adx: Optional[float]
    regime: Optional[str]
    candle_reliable: bool


class TimeframeIndicatorState:
    """Maintain indicator history for a single symbol and timeframe."""

    def __init__(
        self,
        *,
        symbol: str,
        timeframe: str,
        rsi_period: int = 14,
        macd_fast_period: int = 12,
        macd_slow_period: int = 26,
        macd_signal_period: int = 9,
        bollinger_period: int = 20,
        bollinger_std_dev: float = 2.0,
        ema_fast_period: int = 9,
        ema_slow_period: int = 21,
        atr_period: int = 14,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.rsi_period = rsi_period
        self.macd_fast_period = macd_fast_period
        self.macd_slow_period = macd_slow_period
        self.macd_signal_period = macd_signal_period
        self.bollinger_period = bollinger_period
        self.bollinger_std_dev = bollinger_std_dev
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period
        self.atr_period = atr_period
        self.adx_period = 14  # Standard ADX period
        self._candles: list[Candle] = []
        self._latest_snapshot: Optional[IndicatorSnapshot] = None

    @property
    def candles(self) -> list[Candle]:
        return list(self._candles)

    @property
    def latest_snapshot(self) -> Optional[IndicatorSnapshot]:
        return self._latest_snapshot

    def process(self, candle: Candle) -> Optional[IndicatorSnapshot]:
        if candle.symbol != self.symbol:
            raise ValueError(f"Candle symbol {candle.symbol} does not match indicator symbol {self.symbol}")
        if candle.timeframe != self.timeframe:
            raise ValueError(f"Candle timeframe {candle.timeframe} does not match indicator timeframe {self.timeframe}")
        if candle.discarded:
            return None

        self._candles.append(candle)
        closes = [item.close for item in self._candles]
        highs = [item.high for item in self._candles]
        lows = [item.low for item in self._candles]

        rsi_values = _rsi_series(closes, self.rsi_period)
        macd_line, macd_signal, macd_histogram = _macd_series(
            closes,
            self.macd_fast_period,
            self.macd_slow_period,
            self.macd_signal_period,
        )
        bollinger_middle, bollinger_upper, bollinger_lower = _bollinger_series(
            closes,
            self.bollinger_period,
            self.bollinger_std_dev,
        )
        ema_fast = _ema_series(closes, self.ema_fast_period)
        ema_slow = _ema_series(closes, self.ema_slow_period)
        atr_values = _atr_series(highs, lows, closes, self.atr_period)
        adx_values = _adx_series(highs, lows, closes, self.adx_period)

        latest_index = len(self._candles) - 1
        fast_value = ema_fast[latest_index]
        slow_value = ema_slow[latest_index]
        previous_fast = ema_fast[latest_index - 1] if latest_index > 0 else None
        previous_slow = ema_slow[latest_index - 1] if latest_index > 0 else None
        alignment: Optional[str]
        cross: Optional[str]
        if fast_value is None or slow_value is None:
            alignment = None
            cross = None
        elif fast_value > slow_value:
            alignment = "bullish"
            if previous_fast is not None and previous_slow is not None and previous_fast <= previous_slow:
                cross = "bullish"
            else:
                cross = None
        elif fast_value < slow_value:
            alignment = "bearish"
            if previous_fast is not None and previous_slow is not None and previous_fast >= previous_slow:
                cross = "bearish"
            else:
                cross = None
        else:
            alignment = "neutral"
            cross = None

        # Classify regime based on ADX
        adx_value = adx_values[latest_index]
        regime: Optional[str] = None
        if adx_value is not None:
            if adx_value < 25:
                regime = "RANGING"
            elif adx_value < 50:
                regime = "TRENDING"
            else:
                regime = "STRONG_TREND"
        
        snapshot = IndicatorSnapshot(
            symbol=self.symbol,
            timeframe=self.timeframe,
            candle_start_time_utc=candle.start_time_utc,
            candle_end_time_utc=candle.end_time_utc,
            close=candle.close,
            rsi=rsi_values[latest_index],
            macd=macd_line[latest_index],
            macd_signal=macd_signal[latest_index],
            macd_histogram=macd_histogram[latest_index],
            bollinger_middle=bollinger_middle[latest_index],
            bollinger_upper=bollinger_upper[latest_index],
            bollinger_lower=bollinger_lower[latest_index],
            ema_fast=fast_value,
            ema_slow=slow_value,
            ema_alignment=alignment,
            ema_cross=cross,
            atr=atr_values[latest_index],
            adx=adx_value,
            regime=regime,
            candle_reliable=candle.is_reliable,
        )
        self._latest_snapshot = snapshot
        return snapshot


class IndicatorManager:
    """Maintain independent indicator states for each supported timeframe."""

    def __init__(self, *, symbol: str, timeframes: Iterable[str] = ("5m", "1h")) -> None:
        self.symbol = symbol
        self.states = {timeframe: TimeframeIndicatorState(symbol=symbol, timeframe=timeframe) for timeframe in timeframes}

    def process(self, candle: Candle) -> Optional[IndicatorSnapshot]:
        state = self.states.get(candle.timeframe)
        if state is None:
            raise ValueError(f"Unsupported timeframe: {candle.timeframe}")
        return state.process(candle)

    def latest(self, timeframe: str) -> Optional[IndicatorSnapshot]:
        state = self.states.get(timeframe)
        if state is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        return state.latest_snapshot
