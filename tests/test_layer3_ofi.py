"""Tests for Layer 3 order flow imbalance calculations."""

from __future__ import annotations

from shared.schemas import ScoredTick

from services.layer3_strategy.ofi import OrderFlowImbalanceState


def _build_tick(index: int, mid_price: float, *, volume: float = 1.0) -> ScoredTick:
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
        system_state="NORMAL",
        mad_guard_triggered=False,
    )


def test_ofi_turns_positive_on_monotone_rising_prices() -> None:
    state = OrderFlowImbalanceState(symbol="BTC-USDT", window_size=50)

    snapshot = None
    for index in range(60):
        snapshot = state.process(_build_tick(index, 100.0 + index, volume=1.0))

    assert snapshot is not None
    assert snapshot.tick_count == 50
    assert snapshot.ofi > 0.0
    assert snapshot.ofi <= 1.0
    assert snapshot.buy_volume > 0.0
    assert snapshot.sell_volume == 0.0


def test_ofi_turns_negative_on_monotone_falling_prices() -> None:
    state = OrderFlowImbalanceState(symbol="BTC-USDT", window_size=50)

    snapshot = None
    for index in range(60):
        snapshot = state.process(_build_tick(index, 200.0 - index, volume=1.0))

    assert snapshot is not None
    assert snapshot.tick_count == 50
    assert snapshot.ofi < 0.0
    assert snapshot.ofi >= -1.0
    assert snapshot.buy_volume == 0.0
    assert snapshot.sell_volume > 0.0


def test_ofi_uses_a_rolling_window_not_the_full_history() -> None:
    state = OrderFlowImbalanceState(symbol="BTC-USDT", window_size=50)

    for index in range(50):
        state.process(_build_tick(index, 100.0 + index, volume=1.0))

    rising_snapshot = state.process(_build_tick(50, 150.0, volume=1.0))
    assert rising_snapshot.ofi > 0.0
    assert rising_snapshot.tick_count == 50

    snapshot = None
    for index in range(51, 101):
        snapshot = state.process(_build_tick(index, 150.0 - (index - 50), volume=1.0))

    assert snapshot is not None
    assert snapshot.tick_count == 50
    assert snapshot.ofi < 0.0