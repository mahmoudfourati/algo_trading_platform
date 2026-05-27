"""Absolute Threshold Detector — Tier 1, fires from tick 1.

Catches extreme single-tick events that don't need any history:
  - Flash crashes / spikes  (price jump > N bps)
  - Liquidity crises        (spread > N bps)
  - Volume explosions       (volume > N× rolling average)

All thresholds are intentionally generous defaults — tune via constructor.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Optional

from .base import DetectorResult


class AbsoluteThresholdDetector:
    """Hard-limit checks for extreme single-tick events.

    Volume comparison requires a short rolling average (default 300 ticks ≈ 5 min
    at 1 tick/s). Everything else is purely stateless.
    """

    def __init__(
        self,
        *,
        price_jump_bps: float = 200.0,   # Raised from 100 - 2% moves are normal in crypto
        spread_bps: float = 100.0,        # Raised from 50 - wider spreads in crypto
        volume_spike_x: float = 15.0,     # Raised from 10 - volume spikes are common
        volume_avg_window: int = 300,
    ) -> None:
        self._price_jump_bps = price_jump_bps
        self._spread_bps = spread_bps
        self._volume_spike_x = volume_spike_x

        # Rolling volume average
        self._vol_buf: Deque[float] = deque(maxlen=volume_avg_window)
        self._vol_sum: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _vol_avg(self) -> float:
        if not self._vol_buf:
            return 1.0
        return self._vol_sum / len(self._vol_buf)

    def _update_vol(self, volume: float) -> None:
        if len(self._vol_buf) == self._vol_buf.maxlen:
            self._vol_sum -= self._vol_buf[0]
        self._vol_buf.append(volume)
        self._vol_sum += volume

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
        """Evaluate hard limits and return the worst (highest-score) breach.

        Volume average is updated *before* comparison so the current tick
        is included in future averages but the comparison uses the
        pre-update average — avoids self-inflating the baseline.
        """
        avg_vol = self._vol_avg()
        self._update_vol(volume)

        # --- flash crash / spike ---
        if abs(price_jump_bps) > self._price_jump_bps:
            # Scale: at 2× threshold → score 0.75, at 3× → 0.90
            raw = abs(price_jump_bps) / self._price_jump_bps
            score = min(0.95, 0.40 + 0.35 * (raw - 1.0))
            return DetectorResult(score=score, triggered=True, reason="flash_crash_price")

        # --- liquidity crisis (spread) ---
        if spread_bps > self._spread_bps:
            raw = spread_bps / self._spread_bps
            score = min(0.95, 0.40 + 0.30 * (raw - 1.0))
            return DetectorResult(score=score, triggered=True, reason="liquidity_spread")

        # --- volume explosion ---
        if avg_vol > 0 and (volume / avg_vol) > self._volume_spike_x:
            raw = volume / avg_vol / self._volume_spike_x
            score = min(0.95, 0.35 + 0.25 * (raw - 1.0))
            return DetectorResult(score=score, triggered=True, reason="volume_spike")

        # --- nothing triggered ---
        # Return a proportional score for the closest breach so the
        # fusion layer has a smooth signal, not just 0/1.
        proximity = max(
            abs(price_jump_bps) / self._price_jump_bps,
            spread_bps / self._spread_bps,
            (volume / avg_vol / self._volume_spike_x) if avg_vol > 0 else 0.0,
        )
        return DetectorResult(
            score=min(0.49, proximity * 0.49),
            triggered=False,
            reason="normal",
        )