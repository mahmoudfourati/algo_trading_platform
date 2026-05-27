"""MAD (Median Absolute Deviation) Detector — Tier 2.

Why MAD over z-score for crypto:
  Crypto returns have fat tails. Z-score assumes near-Gaussian data, which means
  it *systematically underestimates* how likely 4-5σ events are in reality.
  MAD uses the median instead of the mean, making it robust to the very outliers
  it's trying to detect — no self-contamination.

Regime-aware multiplier (k):
  Regime 0 (low vol)  → k = 4.0  (tight: large moves are suspicious)
  Regime 1 (high vol) → k = 8.0  (loose: large moves are normal)

  These match the values that were already validated in the original spec.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from typing import Deque

from .base import DetectorResult

# Consistency constant: converts MAD to equivalent σ under Gaussian assumption.
# 1 / Φ⁻¹(0.75) ≈ 1.4826
_MAD_TO_SIGMA = 1.4826

# Minimum samples before we trust the MAD estimate
_MIN_SAMPLES = 30


class MADDetector:
    """Rolling MAD detector on log returns with regime-adaptive threshold."""

    def __init__(
        self,
        *,
        window: int = 100,
        k_low_vol: float = 6.0,    # Raised from 4.0 - crypto has fat tails
        k_high_vol: float = 10.0,  # Raised from 8.0 - high vol regime needs more slack
    ) -> None:
        self._window = window
        self._k = {0: k_low_vol, 1: k_high_vol}
        self._buf: Deque[float] = deque(maxlen=window)

    def update(self, *, ret: float, regime: int) -> DetectorResult:
        """Add a log return and score it against the rolling MAD.

        Args:
            ret    : log return for this tick
            regime : HMM regime (0=low vol, 1=high vol)

        Returns:
            DetectorResult with score in [0, 1]
        """
        self._buf.append(ret)

        if len(self._buf) < _MIN_SAMPLES:
            # Not enough history — return a neutral score, not 0.
            # Using 0.0 here would suppress the detector signal during early
            # ticks when it might matter. 0.25 is a slightly below-neutral
            # placeholder that won't distort the ensemble.
            return DetectorResult(score=0.25, triggered=False, reason="warming_up")

        data = list(self._buf)
        med = statistics.median(data)
        mad = statistics.median([abs(x - med) for x in data])

        if mad < 1e-12:
            # Flat market (e.g., stablecoin tick storm) — any non-zero move
            # is suspicious, but we can't score it meaningfully without spread.
            # Return moderate score to avoid false alarms.
            return DetectorResult(score=0.3, triggered=False, reason="flat_market")

        # MAD score: how many "robust sigmas" is this return from the median?
        robust_z = abs(ret - med) / (_MAD_TO_SIGMA * mad)

        # Regime-aware threshold
        k = self._k.get(regime, self._k[0])

        if robust_z > k:
            # Scale: at k → 0.50, at 2k → 0.85, cap at 0.95
            score = min(0.95, 0.50 + 0.35 * ((robust_z - k) / k))
            return DetectorResult(score=score, triggered=True, reason="mad_outlier")

        # Proportional score below threshold
        score = min(0.49, (robust_z / k) * 0.49)
        return DetectorResult(score=score, triggered=False, reason="normal")