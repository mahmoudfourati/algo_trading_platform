"""Layer 4 risk management engine.

This module applies the blueprint's pre-execution checks, ATR-based stop-loss
and take-profit assignment, and the NORMAL/REDUCED/HALTED circuit breaker
state machine before a signal is converted into an approved order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from shared.schemas import ApprovedOrder, SystemState

from services.layer3_strategy.signals import SignalDirection, TradeSignal


CircuitBreakerState = Literal["NORMAL", "REDUCED", "HALTED"]


@dataclass(frozen=True)
class RiskManagerConfig:
    """Configurable thresholds for Layer 4 risk checks."""

    trust_floor: float = 0.40
    max_position_size_pct: float = 0.20
    max_trade_loss_pct: float = 0.02
    max_portfolio_exposure_pct: float = 0.60
    consecutive_loss_pause_threshold: int = 5
    consecutive_loss_recovery_ticks: int = 10
    pause_duration_minutes: int = 30
    daily_loss_limit_pct: float = 0.08
    drawdown_reduce_threshold_pct: float = 0.05
    drawdown_release_threshold_pct: float = 0.03
    reduced_state_size_multiplier: float = 0.5


@dataclass
class RiskState:
    """Mutable circuit breaker and capital tracking state."""

    circuit_breaker_state: CircuitBreakerState = "NORMAL"
    pause_until_utc: Optional[int] = None
    consecutive_losing_trades: int = 0
    normal_tick_streak: int = 0
    session_start_equity: float = 1.0
    current_equity: float = 1.0
    peak_equity: float = 1.0
    latest_drawdown_pct: float = 0.0
    daily_loss_halted: bool = False
    last_loss_direction: Optional[SignalDirection] = None
    last_state_reason: str = ""
    last_approved_order: Optional[ApprovedOrder] = None
    alert_events: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RiskDecision:
    """Result of evaluating a trade signal against Layer 4 rules."""

    approved: bool
    circuit_breaker_state: CircuitBreakerState
    reason: str
    approved_order: Optional[ApprovedOrder] = None
    adjusted_size_pct: float = 0.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    alerts: tuple[str, ...] = ()


DEFAULT_RISK_MANAGER_CONFIG = RiskManagerConfig()


@dataclass
class Layer4Telemetry:
    """Counters describing Layer 4 decision behavior."""

    market_observations: int = 0
    state_normal: int = 0
    state_reduced: int = 0
    state_halted: int = 0
    signals_evaluated: int = 0
    approved_orders: int = 0
    rejected_orders: int = 0
    close_all_orders: int = 0
    transition_normal_to_reduced: int = 0
    transition_normal_to_halted: int = 0
    transition_reduced_to_normal: int = 0
    transition_reduced_to_halted: int = 0
    transition_halted_to_normal: int = 0
    transition_halted_to_reduced: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)


class Layer4RiskEngine:
    """Apply Layer 4 checks, size adjustments, and circuit breaker updates."""

    def __init__(self, *, config: RiskManagerConfig = DEFAULT_RISK_MANAGER_CONFIG, starting_equity: float = 1.0) -> None:
        if starting_equity <= 0.0:
            raise ValueError("starting_equity must be positive")
        self.config = config
        self.state = RiskState(session_start_equity=starting_equity, current_equity=starting_equity, peak_equity=starting_equity)
        self.telemetry = Layer4Telemetry()

    def observe_market(self, *, timestamp_utc: int, equity: float, upstream_state: SystemState) -> RiskState:
        """Refresh capital metrics and the circuit-breaker state from market context."""

        previous_state = self.state.circuit_breaker_state
        self.state.current_equity = equity
        self.state.peak_equity = max(self.state.peak_equity, equity)
        self.state.latest_drawdown_pct = self._drawdown_pct(equity)

        if equity <= self.state.session_start_equity * (1.0 - self.config.daily_loss_limit_pct):
            self.state.daily_loss_halted = True

        qualifying_normal = (
            upstream_state == "NORMAL"
            and not self.state.daily_loss_halted
            and self.state.latest_drawdown_pct < self.config.drawdown_release_threshold_pct
            and (self.state.pause_until_utc is None or timestamp_utc >= self.state.pause_until_utc)
        )

        if qualifying_normal:
            self.state.normal_tick_streak += 1
        else:
            self.state.normal_tick_streak = 0

        if self.state.daily_loss_halted:
            self._set_state("HALTED", "daily_loss_limit")
            self._record_market_observation(previous_state)
            return self.state

        if upstream_state == "HALT":
            self._set_state("HALTED", "upstream_halt")
            self._record_market_observation(previous_state)
            return self.state

        if self.state.consecutive_losing_trades >= self.config.consecutive_loss_pause_threshold:
            if self.state.pause_until_utc is None:
                self.state.pause_until_utc = timestamp_utc + self.config.pause_duration_minutes * 60_000
            self._set_state("HALTED", "loss_streak_pause")
            if self._can_recover(timestamp_utc):
                self._recover_from_pause()
            self._record_market_observation(previous_state)
            return self.state

        if self._needs_reduced_state():
            if self.state.pause_until_utc is None:
                self.state.pause_until_utc = timestamp_utc + self.config.pause_duration_minutes * 60_000
            self._set_state("REDUCED", self._reduced_reason())
            if self._can_recover(timestamp_utc):
                self._recover_from_pause()
            self._record_market_observation(previous_state)
            return self.state

        if self.state.circuit_breaker_state in {"REDUCED", "HALTED"} and self._can_recover(timestamp_utc):
            self._recover_from_pause()
            self._record_market_observation(previous_state)
            return self.state

        self._set_state("NORMAL", "normal")
        self._record_market_observation(previous_state)
        return self.state

    def register_closed_trade(self, *, realized_pnl_pct: float, direction: SignalDirection, timestamp_utc: int) -> RiskState:
        """Update the streak counters after a simulated trade closes."""

        if realized_pnl_pct < 0.0:
            self.state.consecutive_losing_trades += 1
            self.state.last_loss_direction = direction
        else:
            self.state.consecutive_losing_trades = 0
            self.state.last_loss_direction = None

        self.state.current_equity += realized_pnl_pct
        self.observe_market(timestamp_utc=timestamp_utc, equity=self.state.current_equity, upstream_state="NORMAL")
        return self.state

    def evaluate_signal(
        self,
        signal: TradeSignal,
        *,
        reference_price: float,
        current_portfolio_exposure_pct: float,
        timestamp_utc: Optional[int] = None,
    ) -> RiskDecision:
        """Apply the eight pre-execution checks to a signal."""

        self.telemetry.signals_evaluated += 1
        effective_timestamp = signal.timestamp_utc if timestamp_utc is None else timestamp_utc
        circuit_state = self.state.circuit_breaker_state

        if signal.direction == "HOLD":
            return self._reject("hold signal", circuit_state)
        if circuit_state == "HALTED":
            return self._reject("circuit breaker halted", circuit_state)
        if signal.system_state == "HALT":
            return self._reject("upstream system_state=HALT", circuit_state)
        if signal.system_state == "DEGRADED" and signal.direction != "CLOSE_ALL":
            return self._reject("upstream system_state=DEGRADED", circuit_state)
        if signal.direction != "CLOSE_ALL" and signal.trust_score < self.config.trust_floor:
            return self._reject("trust floor breached", circuit_state)

        if signal.direction == "CLOSE_ALL":
            self.telemetry.close_all_orders += 1
            return self._build_close_all_decision(
                signal,
                current_portfolio_exposure_pct=current_portfolio_exposure_pct,
                circuit_state=circuit_state,
                timestamp_utc=effective_timestamp,
            )

        atr = self._extract_primary_atr(signal)
        if atr is None or atr <= 0.0:
            return self._reject("missing atr", circuit_state)
        if reference_price <= 0.0:
            return self._reject("invalid reference price", circuit_state)

        size_pct = min(signal.size_pct, self.config.max_position_size_pct)
        risk_adjustments: list[str] = []
        if signal.size_pct > self.config.max_position_size_pct:
            risk_adjustments.append("position size capped at 20%")

        if circuit_state == "REDUCED":
            if self.state.last_loss_direction is not None and signal.direction == self.state.last_loss_direction:
                return self._reject("reduced state blocks same-direction trades", circuit_state)
            size_pct *= self.config.reduced_state_size_multiplier
            risk_adjustments.append("reduced state size cut by 50%")

        stop_loss_price, take_profit_price = self._compute_stops(signal.direction, reference_price, atr)
        per_unit_loss_pct = abs(reference_price - stop_loss_price) / reference_price
        trade_loss_pct = size_pct * per_unit_loss_pct
        if trade_loss_pct > self.config.max_trade_loss_pct:
            if per_unit_loss_pct <= 0.0:
                return self._reject("invalid atr risk calculation", circuit_state)
            size_pct *= self.config.max_trade_loss_pct / trade_loss_pct
            risk_adjustments.append("per-trade loss resized to 2% cap")

        if current_portfolio_exposure_pct + size_pct > self.config.max_portfolio_exposure_pct:
            return self._reject("portfolio exposure cap breached", circuit_state)
        if size_pct <= 0.0:
            return self._reject("non-positive approved size", circuit_state)

        order = ApprovedOrder(
            symbol=signal.symbol,
            direction=signal.direction if signal.direction in {"LONG", "SHORT"} else "CLOSE_ALL",
            size_pct=size_pct,
            signal_strength=signal.signal_strength,
            confluence=signal.confluence,
            ofi=signal.ofi,
            trust_score=signal.trust_score,
            timestamp_utc=effective_timestamp,
            entry_price=reference_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            atr=atr,
            system_state=signal.system_state,
            circuit_breaker_state=circuit_state,
            portfolio_exposure_pct=current_portfolio_exposure_pct + size_pct,
            primary_timeframe_snapshot=dict(signal.indicator_snapshots.get("primary", {})),
            higher_timeframe_snapshot=dict(signal.indicator_snapshots.get("higher", {})),
            candle_reliability=dict(signal.candle_reliability),
            risk_adjustments=risk_adjustments,
            reason="approved" if not risk_adjustments else "; ".join(risk_adjustments),
        )
        self.telemetry.approved_orders += 1
        self.state.last_approved_order = order
        return RiskDecision(
            approved=True,
            circuit_breaker_state=circuit_state,
            reason=order.reason,
            approved_order=order,
            adjusted_size_pct=size_pct,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            alerts=tuple(self.state.alert_events),
        )

    def _build_close_all_decision(
        self,
        signal: TradeSignal,
        *,
        current_portfolio_exposure_pct: float,
        circuit_state: CircuitBreakerState,
        timestamp_utc: int,
    ) -> RiskDecision:
        order = ApprovedOrder(
            symbol=signal.symbol,
            direction="CLOSE_ALL",
            size_pct=max(0.0, min(current_portfolio_exposure_pct, self.config.max_portfolio_exposure_pct)),
            signal_strength=signal.signal_strength,
            confluence=signal.confluence,
            ofi=signal.ofi,
            trust_score=signal.trust_score,
            timestamp_utc=timestamp_utc,
            entry_price=0.0,
            stop_loss_price=None,
            take_profit_price=None,
            atr=None,
            system_state=signal.system_state,
            circuit_breaker_state=circuit_state,
            portfolio_exposure_pct=current_portfolio_exposure_pct,
            primary_timeframe_snapshot=dict(signal.indicator_snapshots.get("primary", {})),
            higher_timeframe_snapshot=dict(signal.indicator_snapshots.get("higher", {})),
            candle_reliability=dict(signal.candle_reliability),
            risk_adjustments=["close all"],
            reason="approved close all",
        )
        self.state.last_approved_order = order
        return RiskDecision(
            approved=True,
            circuit_breaker_state=circuit_state,
            reason=order.reason,
            approved_order=order,
            adjusted_size_pct=order.size_pct,
            alerts=tuple(self.state.alert_events),
        )

    def _compute_stops(self, direction: SignalDirection, reference_price: float, atr: float) -> tuple[float, float]:
        if direction == "LONG":
            return reference_price - (1.5 * atr), reference_price + (2.5 * atr)
        return reference_price + (1.5 * atr), reference_price - (2.5 * atr)

    def _extract_primary_atr(self, signal: TradeSignal) -> Optional[float]:
        primary_snapshot = signal.indicator_snapshots.get("primary", {})
        atr = primary_snapshot.get("atr") if isinstance(primary_snapshot, dict) else None
        if atr is None:
            return None
        try:
            return float(atr)
        except (TypeError, ValueError):
            return None

    def _drawdown_pct(self, equity: float) -> float:
        if self.state.peak_equity <= 0.0:
            return 0.0
        return max(0.0, (self.state.peak_equity - equity) / self.state.peak_equity)

    def _needs_reduced_state(self) -> bool:
        return (
            3 <= self.state.consecutive_losing_trades < self.config.consecutive_loss_pause_threshold
            or self.state.latest_drawdown_pct > self.config.drawdown_reduce_threshold_pct
            or self._drawdown_in_reduced_band()
        )

    def _drawdown_in_reduced_band(self) -> bool:
        return 0.03 <= self.state.latest_drawdown_pct <= self.config.drawdown_reduce_threshold_pct

    def _reduced_reason(self) -> str:
        if self.state.consecutive_losing_trades >= 3:
            return "loss_streak_reduced"
        return "drawdown_reduced"

    def _can_recover(self, timestamp_utc: int) -> bool:
        cooldown_elapsed = self.state.pause_until_utc is None or timestamp_utc >= self.state.pause_until_utc
        return (
            cooldown_elapsed
            and self.state.normal_tick_streak >= self.config.consecutive_loss_recovery_ticks
            and self.state.latest_drawdown_pct < self.config.drawdown_release_threshold_pct
            and not self.state.daily_loss_halted
        )

    def _recover_from_pause(self) -> None:
        self.state.circuit_breaker_state = "NORMAL"
        self.state.pause_until_utc = None
        self.state.consecutive_losing_trades = 0
        self.state.normal_tick_streak = 0
        self.state.last_loss_direction = None
        self.state.last_state_reason = "recovered"

    def _set_state(self, state: CircuitBreakerState, reason: str) -> None:
        self.state.circuit_breaker_state = state
        self.state.last_state_reason = reason
        if reason not in self.state.alert_events:
            self.state.alert_events.append(reason)

    def _reject(self, reason: str, circuit_state: CircuitBreakerState) -> RiskDecision:
        self.telemetry.rejected_orders += 1
        self.telemetry.rejection_reasons[reason] = self.telemetry.rejection_reasons.get(reason, 0) + 1
        return RiskDecision(approved=False, circuit_breaker_state=circuit_state, reason=reason, alerts=tuple(self.state.alert_events))

    def _record_market_observation(self, previous_state: CircuitBreakerState) -> None:
        current_state = self.state.circuit_breaker_state
        self.telemetry.market_observations += 1
        if current_state == "NORMAL":
            self.telemetry.state_normal += 1
        elif current_state == "REDUCED":
            self.telemetry.state_reduced += 1
        elif current_state == "HALTED":
            self.telemetry.state_halted += 1

        if previous_state == current_state:
            return

        transition_key = f"transition_{previous_state.lower()}_to_{current_state.lower()}"
        if hasattr(self.telemetry, transition_key):
            setattr(self.telemetry, transition_key, getattr(self.telemetry, transition_key) + 1)

    def get_telemetry(self) -> dict[str, object]:
        """Return a flat snapshot for reporting."""

        data = {
            "market_observations": self.telemetry.market_observations,
            "state_normal": self.telemetry.state_normal,
            "state_reduced": self.telemetry.state_reduced,
            "state_halted": self.telemetry.state_halted,
            "signals_evaluated": self.telemetry.signals_evaluated,
            "approved_orders": self.telemetry.approved_orders,
            "rejected_orders": self.telemetry.rejected_orders,
            "close_all_orders": self.telemetry.close_all_orders,
            "transition_normal_to_reduced": self.telemetry.transition_normal_to_reduced,
            "transition_normal_to_halted": self.telemetry.transition_normal_to_halted,
            "transition_reduced_to_normal": self.telemetry.transition_reduced_to_normal,
            "transition_reduced_to_halted": self.telemetry.transition_reduced_to_halted,
            "transition_halted_to_normal": self.telemetry.transition_halted_to_normal,
            "transition_halted_to_reduced": self.telemetry.transition_halted_to_reduced,
        }
        for reason, count in sorted(self.telemetry.rejection_reasons.items()):
            data[f"reject_{reason.replace(' ', '_').replace('-', '_')}"] = count
        return data


__all__ = [
    "CircuitBreakerState",
    "Layer4RiskEngine",
    "RiskDecision",
    "RiskManagerConfig",
    "RiskState",
]