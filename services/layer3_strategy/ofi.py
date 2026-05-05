"""Tick-level order flow imbalance for Layer 3 strategy confirmation.

Order flow imbalance is computed from the raw tick stream over a rolling
window of 50 ticks and remains bounded to the range [-1, 1].
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

from shared.schemas import ScoredTick


@dataclass(frozen=True)
class OrderFlowImbalanceSnapshot:
    """Computed OFI state for the current tick window."""

    symbol: str
    timestamp_utc: int
    mid_price: float
    ofi: float
    buy_volume: float
    sell_volume: float
    tick_count: int
    window_size: int


class OrderFlowImbalanceState:
    """Maintain rolling OFI over the last N ticks for one symbol."""

    def __init__(self, *, symbol: str, window_size: int = 50) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")

        self.symbol = symbol
        self.window_size = window_size
        self._signed_volumes: Deque[float] = deque()
        self._previous_mid_price: Optional[float] = None

    def reset(self) -> None:
        """Clear rolling state without changing configuration."""

        self._signed_volumes.clear()
        self._previous_mid_price = None

    def process(self, tick: ScoredTick, *, volume: Optional[float] = None) -> OrderFlowImbalanceSnapshot:
        """Ingest one tick and return the updated OFI snapshot."""

        if tick.symbol != self.symbol:
            raise ValueError(f"Tick symbol {tick.symbol} does not match OFI symbol {self.symbol}")

        tick_volume = self._resolve_volume(tick, volume)
        if self._previous_mid_price is None:
            signed_volume = 0.0
        elif tick.mid_price > self._previous_mid_price:
            signed_volume = tick_volume
        else:
            signed_volume = -tick_volume

        self._previous_mid_price = tick.mid_price
        self._signed_volumes.append(signed_volume)
        if len(self._signed_volumes) > self.window_size:
            self._signed_volumes.popleft()

        buy_volume = sum(value for value in self._signed_volumes if value > 0.0)
        sell_volume = sum(-value for value in self._signed_volumes if value < 0.0)
        denominator = buy_volume + sell_volume
        ofi = 0.0 if denominator == 0.0 else (buy_volume - sell_volume) / denominator

        return OrderFlowImbalanceSnapshot(
            symbol=self.symbol,
            timestamp_utc=tick.timestamp_utc,
            mid_price=float(tick.mid_price),
            ofi=ofi,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            tick_count=len(self._signed_volumes),
            window_size=self.window_size,
        )

    @staticmethod
    def _resolve_volume(tick: ScoredTick, volume: Optional[float]) -> float:
        candidate = volume if volume is not None else tick.volume_24h
        if candidate is None:
            return 1.0
        resolved = float(candidate)
        return resolved if resolved > 0.0 else 0.0
