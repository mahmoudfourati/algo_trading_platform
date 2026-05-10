"""Tests for the Layer 3 Kafka-facing service wiring."""

from __future__ import annotations

from dataclasses import dataclass

from shared.schemas import ScoredTick

from services.layer3_strategy.indicators import IndicatorSnapshot
from services.layer3_strategy.ofi import OrderFlowImbalanceSnapshot
from services.layer3_strategy.service import Layer3SymbolState


def _tick(index: int, mid_price: float, *, volume: float = 1.0, system_state: str = "NORMAL") -> ScoredTick:
    return ScoredTick(
        symbol="BTC-USDT",
        asset_class="crypto",
        primary_exchange="binance",
        mid_price=mid_price,
        consensus_mid=mid_price,
        volume_24h=volume,
        spread=0.0,
        trust_score=0.95,
        sub_scores={"t1": 1.0},
        used_sources=["binance"],
        divergent_sources=[],
        timestamp_utc=1_700_000_000_000 + index,
        tick_hash=f"hash-{index}",
        anomaly_score=0.05,
        if_score=0.05,
        hst_score=0.05,
        regime=0,
        regime_posterior=[1.0, 0.0],
        system_state=system_state,  # type: ignore[arg-type]
        mad_guard_triggered=False,
    )


@dataclass
class FakePublisher:
    published: list[dict]

    def publish(self, payload: dict) -> None:
        self.published.append(payload)

    def stop(self) -> None:
        return None


def _indicator_snapshot(
    *,
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
        symbol="BTC-USDT",
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


def test_layer3_symbol_state_emits_sized_signal_from_seeded_gate_state() -> None:
    state = Layer3SymbolState(symbol="BTC-USDT")

    state.primary_history.extend(
        [
            _indicator_snapshot(timeframe="5m", close=100.5, rsi=40.0, macd_histogram=0.01, bollinger_middle=101.0, bollinger_upper=102.0, bollinger_lower=100.0, ema_fast=99.5, ema_slow=100.0, ema_alignment="bearish"),
            _indicator_snapshot(timeframe="5m", close=100.2, rsi=35.0, macd_histogram=0.015, bollinger_middle=100.8, bollinger_upper=101.8, bollinger_lower=100.0, ema_fast=99.8, ema_slow=100.1, ema_alignment="bullish", ema_cross="bullish"),
            _indicator_snapshot(timeframe="5m", close=99.4, rsi=30.0, macd_histogram=0.02, bollinger_middle=100.6, bollinger_upper=101.6, bollinger_lower=100.0, ema_fast=100.2, ema_slow=99.9, ema_alignment="bullish"),
        ]
    )
    state.higher_history.extend(
        [
            _indicator_snapshot(timeframe="1h", close=100.8, rsi=57.0, macd_histogram=-0.02, bollinger_middle=101.5, bollinger_upper=103.0, bollinger_lower=99.0, ema_fast=100.0, ema_slow=100.5),
            _indicator_snapshot(timeframe="1h", close=100.2, rsi=50.0, macd_histogram=0.01, bollinger_middle=101.2, bollinger_upper=102.8, bollinger_lower=99.5, ema_fast=100.4, ema_slow=100.2),
        ]
    )
    state.latest_ofi = OrderFlowImbalanceSnapshot(
        symbol="BTC-USDT",
        timestamp_utc=1_700_000_000_000,
        mid_price=100.0,
        ofi=0.25,
        buy_volume=1.0,
        sell_volume=0.0,
        tick_count=50,
        window_size=50,
    )

    signals = state._maybe_emit_signal(tick=_tick(999, 100.0))

    assert len(signals) == 1
    assert signals[0].symbol == "BTC-USDT"
    assert signals[0].direction == "LONG"
    assert signals[0].size_pct > 0.0


def test_layer3_symbol_state_keeps_ofi_and_candles_independent() -> None:
    state = Layer3SymbolState(symbol="BTC-USDT")

    for index in range(80):
        state.ingest_tick(_tick(index, 200.0 - (index * 0.1)))

    assert state.latest_ofi is not None
    assert state.latest_ofi.symbol == "BTC-USDT"
    assert len(state.primary_history) <= 3
    assert len(state.higher_history) <= 2
