"""Candle aggregation for Layer 3 strategy inputs.

The strategy layer consumes `ScoredTick` messages and produces OHLCV candles for
the 5-minute and 1-hour streams while tracking candle reliability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable, Optional

from shared.schemas import ScoredTick, SystemState


TIMEFRAME_TO_MS: dict[str, int] = {
    "5m": 5 * 60 * 1000,
    "1h": 60 * 60 * 1000,
}


def _bucket_start(timestamp_utc: int, timeframe_ms: int) -> int:
    return (int(timestamp_utc) // timeframe_ms) * timeframe_ms


@dataclass(frozen=True)
class Candle:
    """OHLCV candle with reliability metadata."""

    symbol: str
    timeframe: str
    start_time_utc: int
    end_time_utc: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int
    avg_trust_score: float
    max_anomaly_score: float
    is_reliable: bool
    consecutive_unreliable_candles: int
    discarded: bool = False
    system_state_override: Optional[SystemState] = None


@dataclass(frozen=True)
class CandleAggregationEvent:
    """Finalized candle emitted by an aggregator."""

    candle: Candle
    timeframe: str


@dataclass
class _BucketState:
    start_time_utc: int
    ticks: list[ScoredTick] = field(default_factory=list)


class CandleAggregator:
    """Aggregate a single symbol and timeframe into OHLCV candles."""

    def __init__(
        self,
        *,
        symbol: str,
        timeframe: str,
        reliability_trust_floor: float = 0.5,
        reliability_anomaly_ceiling: float = 0.8,
        unreliable_streak_to_degrade: int = 50,
    ) -> None:
        if timeframe not in TIMEFRAME_TO_MS:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        self.symbol = symbol
        self.timeframe = timeframe
        self.timeframe_ms = TIMEFRAME_TO_MS[timeframe]
        self.reliability_trust_floor = reliability_trust_floor
        self.reliability_anomaly_ceiling = reliability_anomaly_ceiling
        self.unreliable_streak_to_degrade = unreliable_streak_to_degrade
        self._bucket: Optional[_BucketState] = None
        self._consecutive_unreliable_candles = 0

    @property
    def consecutive_unreliable_candles(self) -> int:
        return self._consecutive_unreliable_candles

    def process(self, tick: ScoredTick) -> list[CandleAggregationEvent]:
        """Ingest one scored tick and emit any finalized candles."""

        if tick.symbol != self.symbol:
            raise ValueError(f"Tick symbol {tick.symbol} does not match aggregator symbol {self.symbol}")

        bucket_start = _bucket_start(tick.timestamp_utc, self.timeframe_ms)

        if self._bucket is None:
            self._bucket = _BucketState(start_time_utc=bucket_start, ticks=[tick])
            return []

        if bucket_start == self._bucket.start_time_utc:
            self._bucket.ticks.append(tick)
            return []

        finalized = self._finalize_current_bucket()
        self._bucket = _BucketState(start_time_utc=bucket_start, ticks=[tick])
        return finalized

    def flush(self) -> list[CandleAggregationEvent]:
        """Finalize the current bucket at end of stream."""

        if self._bucket is None:
            return []

        finalized = self._finalize_current_bucket()
        self._bucket = None
        return finalized

    def _finalize_current_bucket(self) -> list[CandleAggregationEvent]:
        assert self._bucket is not None
        ticks = list(self._bucket.ticks)
        if not ticks:
            return []

        prices = [float(t.mid_price) for t in ticks]
        volumes = [max(0.0, float(t.volume_24h or 0.0)) for t in ticks]
        trust_scores = [float(t.trust_score) for t in ticks]
        anomaly_scores = [float(t.anomaly_score) for t in ticks]

        tick_count = len(ticks)
        avg_trust_score = mean(trust_scores)
        max_anomaly_score = max(anomaly_scores)
        is_reliable = tick_count >= 3 and avg_trust_score >= self.reliability_trust_floor and max_anomaly_score <= self.reliability_anomaly_ceiling

        if is_reliable:
            self._consecutive_unreliable_candles = 0
        else:
            self._consecutive_unreliable_candles += 1

        candle = Candle(
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_time_utc=self._bucket.start_time_utc,
            end_time_utc=self._bucket.start_time_utc + self.timeframe_ms,
            open=prices[0],
            high=max(prices),
            low=min(prices),
            close=prices[-1],
            volume=sum(volumes),
            tick_count=tick_count,
            avg_trust_score=avg_trust_score,
            max_anomaly_score=max_anomaly_score,
            is_reliable=is_reliable,
            consecutive_unreliable_candles=self._consecutive_unreliable_candles,
            discarded=tick_count < 3,
            system_state_override="DEGRADED" if self._consecutive_unreliable_candles >= self.unreliable_streak_to_degrade else None,
        )
        return [CandleAggregationEvent(candle=candle, timeframe=self.timeframe)]


class CandleAggregationManager:
    """Manage 5m and 1h candle streams for a symbol."""

    def __init__(self, *, symbol: str, timeframes: Iterable[str] = ("5m", "1h")) -> None:
        self.symbol = symbol
        self.aggregators = {timeframe: CandleAggregator(symbol=symbol, timeframe=timeframe) for timeframe in timeframes}

    def process(self, tick: ScoredTick) -> list[CandleAggregationEvent]:
        events: list[CandleAggregationEvent] = []
        for aggregator in self.aggregators.values():
            events.extend(aggregator.process(tick))
        return events

    def flush(self) -> list[CandleAggregationEvent]:
        events: list[CandleAggregationEvent] = []
        for aggregator in self.aggregators.values():
            events.extend(aggregator.flush())
        return events