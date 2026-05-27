"""EWMA Detector — Tier 3, exponentially weighted moving average control chart.

EWMA gives more weight to recent observations while keeping memory of the past.
It catches *small sustained shifts* faster than CUSUM (which waits for accumulation).

Two instances run in parallel:
  - ewma_price  : detects price micro-trends
  - ewma_spread : detects gradual spread widening (order book thinning)

The final score is the max of the two, so either channel can independently trigger.
Spread EWMA is particularly valuable: spread widens *before* price dislocates
in most liquidity crises.

Standard EWMA control chart formula:
  Z_t = λ·x_t + (1-λ)·Z_{t-1}
  UCL/LCL = ±L·σ·sqrt(λ / (2-λ))
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from typing import Deque, Optional

from .base import DetectorResult

_WARMUP = 30


class _EWMAChannel:
    """Single EWMA control chart on one signal."""

    def __init__(self, *, lambda_: float, L: float, history_window: int) -> None:
        self._lambda = lambda_
        self._L = L
        self._buf: Deque[float] = deque(maxlen=history_window)
        self._ewma: Optional[float] = None
        self._mean: float = 0.0
        self._std: float = 1.0
        self._ticks: int = 0

    def update(self, value: float) -> float:
        """Returns anomaly score [0, 1] for this channel."""
        self._ticks += 1
        self._buf.append(value)

        if self._ticks >= _WARMUP:
            self._mean = statistics.mean(self._buf)
            try:
                self._std = statistics.stdev(self._buf)
            except statistics.StatisticsError:
                self._std = 1.0
            if self._std < 1e-9:
                self._std = 1.0

        if self._ticks < _WARMUP:
            return 0.25

        z = (value - self._mean) / self._std

        if self._ewma is None:
            self._ewma = z
        else:
            self._ewma = self._lambda * z + (1.0 - self._lambda) * self._ewma

        # Control limit: L·sqrt(λ / (2-λ))
        control_limit = self._L * math.sqrt(self._lambda / (2.0 - self._lambda))

        if abs(self._ewma) > control_limit:
            excess = abs(self._ewma) - control_limit
            return min(0.95, 0.5 + 0.5 * (excess / control_limit))

        # Proportional inside limits
        return min(0.49, abs(self._ewma) / control_limit * 0.49)


class EWMADetector:
    """Dual EWMA detector: price channel + spread channel.

    Args:
        lambda_ : Smoothing factor (0 < λ ≤ 1). Lower = more memory.
                  0.2 is the standard choice for financial control charts.
        L       : Control limit multiplier (typically 2.7–3.0)
        history_window : Rolling window for mean/std normalisation
    """

    def __init__(
        self,
        *,
        lambda_: float = 0.2,
        L: float = 4.0,  # Raised from 3.0 - less sensitive to normal volatility
        history_window: int = 1000,
    ) -> None:
        self._price_ch = _EWMAChannel(lambda_=lambda_, L=L, history_window=history_window)
        self._spread_ch = _EWMAChannel(lambda_=lambda_, L=L, history_window=history_window)

    def update(
        self,
        *,
        price_jump_bps: float,
        spread_bps: float,
    ) -> DetectorResult:
        """Update both channels and return the higher-scoring result.

        Args:
            price_jump_bps : tick-over-tick price change in basis points
            spread_bps     : current bid-ask spread in basis points

        Returns:
            DetectorResult — score is max of price and spread channels
        """
        price_score = self._price_ch.update(price_jump_bps)
        spread_score = self._spread_ch.update(spread_bps)

        if spread_score >= price_score:
            score = spread_score
            channel = "spread"
        else:
            score = price_score
            channel = "price"

        triggered = score >= 0.5
        reason = f"ewma_{channel}" if triggered else "normal"

        return DetectorResult(score=score, triggered=triggered, reason=reason)