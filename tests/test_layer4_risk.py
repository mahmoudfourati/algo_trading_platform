"""Tests for the Layer 4 risk management engine."""

from __future__ import annotations

from math import isclose

from services.layer3_strategy.signals import TradeSignal
from services.layer4_risk import Layer4RiskEngine


def _signal(
    *,
    direction: str = "LONG",
    size_pct: float = 0.25,
    system_state: str = "NORMAL",
    trust_score: float = 0.95,
    atr: float = 1.0,
    timestamp_utc: int = 1_700_000_000_000,
) -> TradeSignal:
    return TradeSignal(
        symbol="BTC-USDT",
        direction=direction,  # type: ignore[arg-type]
        size_pct=size_pct,
        signal_strength=0.8,
        confluence="FULL",
        ofi=0.2,
        system_state=system_state,  # type: ignore[arg-type]
        timestamp_utc=timestamp_utc,
        indicator_snapshots={"primary": {"atr": atr}, "higher": {"atr": atr}},
        candle_reliability={"primary": True, "higher": True},
        trust_score=trust_score,
        reason="fixture",
    )


def test_upstream_halt_and_degraded_gate_orders() -> None:
    engine = Layer4RiskEngine()

    halted = engine.evaluate_signal(_signal(system_state="HALT"), reference_price=100.0, current_portfolio_exposure_pct=0.0)
    degraded = engine.evaluate_signal(_signal(system_state="DEGRADED"), reference_price=100.0, current_portfolio_exposure_pct=0.0)
    close_all = engine.evaluate_signal(_signal(direction="CLOSE_ALL", system_state="DEGRADED"), reference_price=100.0, current_portfolio_exposure_pct=0.18)

    assert not halted.approved
    assert not degraded.approved
    assert close_all.approved
    assert close_all.approved_order is not None
    assert close_all.approved_order.direction == "CLOSE_ALL"


def test_trust_floor_position_cap_and_loss_cap_are_enforced() -> None:
    engine = Layer4RiskEngine()

    rejected = engine.evaluate_signal(_signal(trust_score=0.2), reference_price=100.0, current_portfolio_exposure_pct=0.0)
    assert not rejected.approved
    assert rejected.reason == "trust floor breached"

    approved = engine.evaluate_signal(_signal(size_pct=0.5, atr=1.0), reference_price=100.0, current_portfolio_exposure_pct=0.0)
    assert approved.approved
    assert approved.adjusted_size_pct == 0.2
    assert approved.approved_order is not None
    assert approved.approved_order.stop_loss_price == 98.5
    assert approved.approved_order.take_profit_price == 102.5

    resized = engine.evaluate_signal(_signal(size_pct=0.5, atr=20.0), reference_price=100.0, current_portfolio_exposure_pct=0.0)
    assert resized.approved
    assert isclose(resized.adjusted_size_pct, 0.06666666666666667, rel_tol=1e-12, abs_tol=1e-12)


def test_portfolio_exposure_cap_rejects_excess_orders() -> None:
    engine = Layer4RiskEngine()

    decision = engine.evaluate_signal(_signal(size_pct=0.2), reference_price=100.0, current_portfolio_exposure_pct=0.55)

    assert not decision.approved
    assert decision.reason == "portfolio exposure cap breached"


def test_consecutive_losses_pause_trading_then_recover_after_cooldown() -> None:
    engine = Layer4RiskEngine()

    for index in range(5):
        engine.register_closed_trade(realized_pnl_pct=-0.01, direction="LONG", timestamp_utc=1_700_000_000_000 + index)

    engine.observe_market(timestamp_utc=1_700_000_300_000, equity=0.95, upstream_state="NORMAL")
    assert engine.state.circuit_breaker_state == "HALTED"
    assert engine.state.pause_until_utc is not None

    recovery_start = engine.state.pause_until_utc
    for offset in range(10):
        engine.observe_market(
            timestamp_utc=recovery_start + 1_000 + offset,
            equity=0.98,
            upstream_state="NORMAL",
        )

    assert engine.state.circuit_breaker_state == "NORMAL"
    assert engine.state.consecutive_losing_trades == 0


def test_drawdown_reduces_sizes_and_daily_loss_halts_for_session() -> None:
    engine = Layer4RiskEngine()

    engine.observe_market(timestamp_utc=1_700_000_400_000, equity=0.94, upstream_state="NORMAL")
    assert engine.state.circuit_breaker_state == "REDUCED"

    reduced = engine.evaluate_signal(_signal(size_pct=0.2), reference_price=100.0, current_portfolio_exposure_pct=0.0)
    assert reduced.approved
    assert reduced.adjusted_size_pct == 0.1

    engine.observe_market(timestamp_utc=1_700_000_500_000, equity=0.91, upstream_state="NORMAL")
    assert engine.state.circuit_breaker_state == "HALTED"

    halted = engine.evaluate_signal(_signal(size_pct=0.2), reference_price=100.0, current_portfolio_exposure_pct=0.0)
    assert not halted.approved


def test_reduced_state_blocks_same_direction_trades() -> None:
    engine = Layer4RiskEngine()
    engine.observe_market(timestamp_utc=1_700_000_600_000, equity=0.94, upstream_state="NORMAL")
    engine.register_closed_trade(realized_pnl_pct=-0.01, direction="LONG", timestamp_utc=1_700_000_600_001)
    engine.observe_market(timestamp_utc=1_700_000_600_002, equity=0.94, upstream_state="NORMAL")

    blocked = engine.evaluate_signal(_signal(direction="LONG", size_pct=0.2), reference_price=100.0, current_portfolio_exposure_pct=0.0)
    allowed = engine.evaluate_signal(_signal(direction="SHORT", size_pct=0.2), reference_price=100.0, current_portfolio_exposure_pct=0.0)

    assert not blocked.approved
    assert allowed.approved
    assert allowed.adjusted_size_pct == 0.1