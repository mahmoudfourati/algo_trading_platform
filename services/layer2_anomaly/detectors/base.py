"""Shared types for all Layer 2 detectors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectorResult:
    """What every detector returns.

    score   : float in [0, 1] — 0 = fully normal, 1 = definite anomaly
    triggered: bool — True when score crosses this detector's own threshold
    reason  : short label used in logs, metrics, and downstream audit trail
              e.g. "flash_crash_price", "mad_outlier", "cusum_drift"
    """

    score: float
    triggered: bool
    reason: str