"""Tests for Layer 3 position sizing."""

from __future__ import annotations

from services.layer3_strategy.signals import TradeSignal
from services.layer3_strategy.sizing import PositionSizingConfig, size_trade_signal


def _signal(*, direction: str, signal_strength: float, confluence: str, system_state: str) -> TradeSignal:
    return TradeSignal(
        symbol="BTC-USDT",
        direction=direction,  # type: ignore[arg-type]
        size_pct=0.0,
        signal_strength=signal_strength,
        confluence=confluence,  # type: ignore[arg-type]
        ofi=0.25,
        system_state=system_state,  # type: ignore[arg-type]
        reason="fixture",
    )


def test_position_size_matches_blueprint_formula_for_normal_full_confluence() -> None:
    signal = _signal(direction="LONG", signal_strength=1.0, confluence="FULL", system_state="NORMAL")

    result = size_trade_signal(signal)

    assert result.state_multiplier == 1.0
    assert result.confluence_multiplier == 1.0
    assert result.size_pct == 0.20
    assert result.signal.size_pct == 0.20


def test_position_size_scales_down_for_conservative_partial_confluence() -> None:
    signal = _signal(direction="SHORT", signal_strength=0.5, confluence="PARTIAL", system_state="CONSERVATIVE")

    result = size_trade_signal(signal)

    assert result.state_multiplier == 0.5
    assert result.confluence_multiplier == 0.5
    assert result.size_pct == 0.025
    assert result.signal.size_pct == 0.025


def test_hold_or_none_confluence_always_results_in_zero_size() -> None:
    hold_signal = _signal(direction="HOLD", signal_strength=0.9, confluence="NONE", system_state="NORMAL")

    result = size_trade_signal(hold_signal)

    assert result.size_pct == 0.0
    assert result.state_multiplier == 0.0
    assert result.confluence_multiplier == 0.0
    assert result.signal.size_pct == 0.0


def test_custom_config_can_override_multipliers() -> None:
    signal = _signal(direction="LONG", signal_strength=0.8, confluence="FULL", system_state="NORMAL")
    config = PositionSizingConfig(
        base_size=0.25,
        normal_state_multiplier=0.9,
        conservative_state_multiplier=0.4,
        full_confluence_multiplier=0.75,
        partial_confluence_multiplier=0.25,
    )

    result = size_trade_signal(signal, config=config)

    assert result.size_pct == 0.135
    assert result.signal.size_pct == 0.135
