"""CUSUM Detector — Tier 3, sustained drift detection.

CUSUM accumulates deviations from the expected mean. Unlike point detectors
(MAD, absolute threshold), CUSUM catches *sustained* shifts — e.g., a market
that's drifting 0.5σ every tick for 20 ticks. No single tick looks anomalous,
but the cumulative picture is.

Key upgrade over the previous implementation:
  - Accepts a *composite* input signal, not just price.
  - Default composite: 0.5×price + 0.3×spread + 0.2×volume
  - This means a liquidity crisis (spread widening gradually) will trigger
    CUSUM even if price hasn't moved yet.

Internally CUSUM tracks two accumulators:
  cusum_pos — detects upward drift (buying pressure, price run-up)
  cusum_neg — detects downward drift (selling pressure, flash crash buildup)
"""

from __future__ import annotations

import statistics
from collections import deque
from typing import Deque

from .base import DetectorResult

_WARMUP = 30  # Ticks needed before statistics are meaningful


class CUSUMDetector:
    """Composite-signal CUSUM drift detector.

    Args:
        threshold_sigma : Detection threshold in sigma units (default 5.0)
        drift           : Allowable slack per tick (default 0.5 sigma)
        w_price         : Weight for price component
        w_spread        : Weight for spread component
        w_volume        : Weight for volume component
        history_window  : Rolling window for mean/std estimation
    """

    def __init__(
        self,
        *,
        threshold_sigma: float = 10.0,  # Raised from 5.0 - crypto is volatile
        drift: float = 0.5,
        w_price: float = 0.5,
        w_spread: float = 0.3,
        w_volume: float = 0.2,
        history_window: int = 1000,
    ) -> None:
        self._threshold = threshold_sigma
        self._drift = drift
        self._w_price = w_price
        self._w_spread = w_spread
        self._w_volume = w_volume

        # Per-signal rolling windows for normalisation
        self._price_buf: Deque[float] = deque(maxlen=history_window)
        self._spread_buf: Deque[float] = deque(maxlen=history_window)
        self._volume_buf: Deque[float] = deque(maxlen=history_window)

        # CUSUM accumulators
        self._cusum_pos: float = 0.0
        self._cusum_neg: float = 0.0

        self._ticks: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _zscore(value: float, buf: Deque[float]) -> float:
        """Compute z-score of value against rolling buffer."""
        if len(buf) < _WARMUP:
            return 0.0
        mean = statistics.mean(buf)
        try:
            std = statistics.stdev(buf)
        except statistics.StatisticsError:
            std = 1.0
        if std < 1e-9:
            return 0.0
        return (value - mean) / std

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        *,
        price_jump_bps: float,
        spread_bps: float,
        volume: float,
    ) -> DetectorResult:
        """Update CUSUM with new tick values.

        Args:
            price_jump_bps : tick-over-tick price change in basis points
            spread_bps     : current bid-ask spread in basis points
            volume         : raw volume (any consistent unit)

        Returns:
            DetectorResult — score in [0, 1]
        """
        self._ticks += 1

        # Update rolling buffers (before z-scoring so current tick is included
        # in future estimates but not in its own z-score)
        z_price = self._zscore(price_jump_bps, self._price_buf)
        z_spread = self._zscore(spread_bps, self._spread_buf)
        z_volume = self._zscore(volume, self._volume_buf)

        self._price_buf.append(price_jump_bps)
        self._spread_buf.append(spread_bps)
        self._volume_buf.append(volume)

        if self._ticks < _WARMUP:
            return DetectorResult(score=0.25, triggered=False, reason="warming_up")

        # Composite z-score
        z = (self._w_price * z_price
             + self._w_spread * z_spread
             + self._w_volume * z_volume)

        # Update CUSUM accumulators
        self._cusum_pos = max(0.0, self._cusum_pos + z - self._drift)
        self._cusum_neg = max(0.0, self._cusum_neg - z - self._drift)

        max_cusum = max(self._cusum_pos, self._cusum_neg)
        direction = "up" if self._cusum_pos >= self._cusum_neg else "down"

        if max_cusum >= self._threshold:
            score = min(0.95, max_cusum / self._threshold)
            # Reset CUSUM after detection to allow detection of next anomaly
            self._cusum_pos = 0.0
            self._cusum_neg = 0.0
            return DetectorResult(
                score=score,
                triggered=True,
                reason=f"cusum_drift_{direction}",
            )

        # Proportional score
        score = min(0.64, (max_cusum / self._threshold) * 0.64)
        return DetectorResult(score=score, triggered=False, reason="normal")

    def reset(self) -> None:
        """Reset CUSUM accumulators (e.g., after a confirmed regime change)."""
        self._cusum_pos = 0.0
        self._cusum_neg = 0.0