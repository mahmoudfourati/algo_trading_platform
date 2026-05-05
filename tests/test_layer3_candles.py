"""Tests for Layer 3 candle aggregation."""

from __future__ import annotations

from services.layer3_strategy.candles import CandleAggregationManager, CandleAggregator
from shared.schemas import ScoredTick


def _tick(ts_ms: int, *, mid_price: float, trust_score: float, anomaly_score: float, symbol: str = "BTCUSDT") -> ScoredTick:
    return ScoredTick(
        symbol=symbol,
        asset_class="crypto",
        primary_exchange="binance",
        mid_price=mid_price,
        consensus_mid=mid_price,
        volume_24h=1000.0,
        spread=0.001,
        trust_score=trust_score,
        sub_scores={"t1": 1.0},
        used_sources=["binance"],
        divergent_sources=[],
        timestamp_utc=ts_ms,
        tick_hash=f"hash-{ts_ms}",
        anomaly_score=anomaly_score,
        if_score=anomaly_score,
        hst_score=anomaly_score,
        regime=0,
        regime_posterior=[1.0, 0.0],
        system_state="NORMAL",
        mad_guard_triggered=False,
    )


def test_candle_aggregator_builds_ohlcv_and_metadata() -> None:
    aggregator = CandleAggregator(symbol="BTCUSDT", timeframe="5m")

    ticks = [
        _tick(0, mid_price=100.0, trust_score=0.8, anomaly_score=0.2),
        _tick(60_000, mid_price=102.0, trust_score=0.9, anomaly_score=0.3),
        _tick(120_000, mid_price=99.0, trust_score=0.85, anomaly_score=0.25),
        _tick(300_000, mid_price=101.0, trust_score=0.88, anomaly_score=0.2),
    ]

    events = []
    for tick in ticks:
        events.extend(aggregator.process(tick))
    events.extend(aggregator.flush())

    assert len(events) == 2

    first = events[0].candle
    assert first.timeframe == "5m"
    assert first.start_time_utc == 0
    assert first.end_time_utc == 300_000
    assert first.open == 100.0
    assert first.high == 102.0
    assert first.low == 99.0
    assert first.close == 99.0
    assert first.tick_count == 3
    assert first.is_reliable is True
    assert first.discarded is False
    assert first.consecutive_unreliable_candles == 0
    assert first.max_anomaly_score == 0.3
    assert first.avg_trust_score > 0.8


def test_candle_aggregator_discards_short_candles_and_tracks_unreliable_streak() -> None:
    aggregator = CandleAggregator(symbol="BTCUSDT", timeframe="5m")

    events = []
    # Build 50 short candles, each with only two ticks.
    for candle_index in range(50):
        base = candle_index * 300_000
        events.extend(
            aggregator.process(_tick(base, mid_price=100.0 + candle_index, trust_score=0.4, anomaly_score=0.8))
        )
        events.extend(
            aggregator.process(_tick(base + 60_000, mid_price=100.5 + candle_index, trust_score=0.45, anomaly_score=0.75))
        )
        events.extend(aggregator.flush())

    discarded_events = [event for event in events if event.candle.discarded]
    assert len(discarded_events) == 50
    assert discarded_events[0].candle.tick_count == 2
    assert discarded_events[0].candle.is_reliable is False
    assert discarded_events[0].candle.consecutive_unreliable_candles == 1
    assert discarded_events[-1].candle.consecutive_unreliable_candles >= 50
    assert discarded_events[-1].candle.system_state_override == "DEGRADED"


def test_manager_emits_5m_and_1h_candles_on_boundary_rollover() -> None:
    manager = CandleAggregationManager(symbol="BTCUSDT")

    ticks = [
        _tick(3_599_000, mid_price=100.0, trust_score=0.8, anomaly_score=0.2),
        _tick(3_599_500, mid_price=101.0, trust_score=0.82, anomaly_score=0.25),
        _tick(3_600_000, mid_price=103.0, trust_score=0.85, anomaly_score=0.3),
        _tick(3_900_000, mid_price=104.0, trust_score=0.86, anomaly_score=0.2),
    ]

    events = []
    for tick in ticks:
        events.extend(manager.process(tick))
    events.extend(manager.flush())

    five_minute = [event.candle for event in events if event.timeframe == "5m"]
    one_hour = [event.candle for event in events if event.timeframe == "1h"]

    assert len(five_minute) >= 2
    assert len(one_hour) == 2
    assert five_minute[0].start_time_utc == 3_300_000
    assert five_minute[0].end_time_utc == 3_600_000
    assert five_minute[1].start_time_utc == 3_600_000
    assert one_hour[0].start_time_utc == 0
    assert one_hour[0].end_time_utc == 3_600_000
    assert one_hour[1].start_time_utc == 3_600_000
    assert one_hour[1].end_time_utc == 7_200_000