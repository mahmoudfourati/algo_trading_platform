"""Layer 3 position sizing helpers.

The sizing step is pure and derives the final capital allocation from the
signal output, the system state, and the confluence level.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from shared.schemas import SystemState

from .signals import ConfluenceLevel, TradeSignal


@dataclass(frozen=True)
class PositionSizingConfig:
    """Configuration for converting a trade signal into a final size."""

    base_size: float = 0.20
    normal_state_multiplier: float = 1.0
    conservative_state_multiplier: float = 0.5
    full_confluence_multiplier: float = 1.0
    partial_confluence_multiplier: float = 0.5


@dataclass(frozen=True)
class PositionSizingResult:
    """Signal with an applied position size plus the sizing components used."""

    signal: TradeSignal
    state_multiplier: float
    confluence_multiplier: float
    size_pct: float


DEFAULT_POSITION_SIZING_CONFIG = PositionSizingConfig()


def size_trade_signal(
    signal: TradeSignal,
    *,
    config: PositionSizingConfig = DEFAULT_POSITION_SIZING_CONFIG,
) -> PositionSizingResult:
    """Apply the blueprint position sizing formula to a trade signal."""

    if signal.direction == "HOLD" or signal.confluence == "NONE":
        sized_signal = replace(signal, size_pct=0.0)
        return PositionSizingResult(signal=sized_signal, state_multiplier=0.0, confluence_multiplier=0.0, size_pct=0.0)

    state_multiplier = _state_multiplier(signal.system_state, config)
    confluence_multiplier = _confluence_multiplier(signal.confluence, config)
    size_pct = _clip01(config.base_size * state_multiplier * confluence_multiplier * _clip01(signal.signal_strength))
    sized_signal = replace(signal, size_pct=size_pct)
    return PositionSizingResult(
        signal=sized_signal,
        state_multiplier=state_multiplier,
        confluence_multiplier=confluence_multiplier,
        size_pct=size_pct,
    )


def _state_multiplier(system_state: SystemState, config: PositionSizingConfig) -> float:
    mapping: Mapping[SystemState, float] = {
        "NORMAL": config.normal_state_multiplier,
        "CONSERVATIVE": config.conservative_state_multiplier,
        "DEGRADED": 0.0,
        "HALT": 0.0,
    }
    return mapping[system_state]


def _confluence_multiplier(confluence: ConfluenceLevel, config: PositionSizingConfig) -> float:
    mapping: Mapping[ConfluenceLevel, float] = {
        "FULL": config.full_confluence_multiplier,
        "PARTIAL": config.partial_confluence_multiplier,
        "NONE": 0.0,
    }
    return mapping[confluence]


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))
