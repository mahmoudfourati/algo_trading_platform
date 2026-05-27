"""Volatility Ratio Detector — Tier 2.

Compares short-window realized volatility to a longer baseline window.
Detects volatility regime shifts *as they happen*, complementing the HMM
which operates on 30-minute buckets and lags by design.

Ratio > 2.0 means current vol is 2× the baseline — regime shift in progress.
Ratio > 4.0 means acute volatility explosion.

This detector does NOT replace the HMM. The HMM tells you *which regime you are in*.
This detector tells you *when you are leaving one*. They are complementary.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque

from .base import DetectorResult

_MIN_SAMPLES = 30  # Need at least this many ticks in short window


class VolatilityRatioDetector:
    """Short-window RV vs long-window RV ratio detector."""

    def __init__(
        self,
        *,
        short_window: int = 30,    # ~30 ticks short window
        long_window: int = 300,    # ~300 ticks baseline
        spike_ratio: float = 3.0,  # Raised from 2.0 - crypto vol doubles frequently
        extreme_ratio: float = 5.0,  # Raised from 4.0
    ) -> None:
        self._short_buf: Deque[float] = deque(maxlen=short_window)
        self._long_buf: Deque[float] = deque(maxlen=long_window)
        self._spike_ratio = spike_ratio
        self._extreme_ratio = extreme_ratio

    @staticmethod
    def _rv(rets: list[float]) -> float:
        """Realized volatility = sqrt(sum of squared returns)."""
        if not rets:
            return 0.0
        return math.sqrt(sum(r * r for r in rets))

    def update(self, *, ret: float) -> DetectorResult:
        """Add a log return and compute the volatility ratio.

        Args:
            ret: log return for this tick

        Returns:
            DetectorResult with score in [0, 1]
        """
        self._short_buf.append(ret)
        self._long_buf.append(ret)

        if len(self._short_buf) < _MIN_SAMPLES:
            return DetectorResult(score=0.25, triggered=False, reason="warming_up")

        rv_short = self._rv(list(self._short_buf))
        rv_long = self._rv(list(self._long_buf))

        if rv_long < 1e-12:
            # Baseline is flat — any short-window vol is anomalous
            if rv_short > 1e-8:
                return DetectorResult(score=0.7, triggered=True, reason="vol_from_zero")
            return DetectorResult(score=0.0, triggered=False, reason="normal")

        ratio = rv_short / rv_long

        if ratio >= self._extreme_ratio:
            score = min(0.95, 0.70 + 0.15 * ((ratio - self._extreme_ratio) / self._extreme_ratio))
            return DetectorResult(score=score, triggered=True, reason="vol_explosion")

        if ratio >= self._spike_ratio:
            # Scale linearly from 0.45 at spike_ratio to 0.70 at extreme_ratio
            progress = (ratio - self._spike_ratio) / (self._extreme_ratio - self._spike_ratio)
            score = 0.45 + 0.25 * progress
            return DetectorResult(score=score, triggered=True, reason="vol_spike")

        # Proportional below threshold
        score = min(0.49, (ratio / self._spike_ratio) * 0.49)
        return DetectorResult(score=score, triggered=False, reason="normal")