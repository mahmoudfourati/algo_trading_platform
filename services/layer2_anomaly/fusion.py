"""Layer 2 Fusion — combines detector scores into one final anomaly score.

Fusion strategy (two tiers):

  COINCIDENCE  (2+ detectors triggered):
    Final score = weighted average of ALL triggered detectors.
    Reason = "coincidence: det1 + det2 [+ det3]"
    Capped at 0.85.
    This is the key multi-signal check — a flash crash shows up in
    AbsoluteThreshold AND MAD AND CUSUM simultaneously.

  NORMAL  (0 or 1 detector triggered):
    Final score = weighted average of all detectors.
    Reason = top-scoring detector's label (or "normal" if all low).
    Capped at 0.70.

Regime modulation:
  The HMM regime shifts the final anomaly threshold in the Decision Gate,
  NOT the scores themselves. Fusion is regime-agnostic; regime feeds the
  gate directly. This keeps concerns separated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .detectors.base import DetectorResult


@dataclass(frozen=True)
class FusionResult:
    """Output of the fusion layer."""

    anomaly_score: float      # Final score [0, 1]
    reason: str               # Human-readable explanation
    triggered_count: int      # How many detectors fired
    max_detector_score: float # Highest individual detector score
    # Individual component scores for observability / Prometheus
    absolute_score: float
    mad_score: float
    vol_ratio_score: float
    cusum_score: float
    ewma_score: float


# Detector weights for weighted-average fusion.
# AbsoluteThreshold and MAD are weighted highest because they are the most
# reliable single-tick signals. CUSUM/EWMA complement with drift detection.
_WEIGHTS: dict[str, float] = {
    "absolute": 0.35,
    "mad": 0.30,
    "vol_ratio": 0.15,
    "cusum": 0.10,
    "ewma": 0.10,
}

_EXTREME_THRESHOLD = 0.95  # Raised from 0.90 to reduce false spikes
_TRIGGER_THRESHOLD = 0.60  # Raised from 0.50 to require stronger signals for coincidence


def fuse(
    *,
    absolute: DetectorResult,
    mad: DetectorResult,
    vol_ratio: DetectorResult,
    cusum: DetectorResult,
    ewma: DetectorResult,
) -> FusionResult:
    """Combine five detector results into a single anomaly score.

    Args:
        absolute  : AbsoluteThresholdDetector result
        mad       : MADDetector result
        vol_ratio : VolatilityRatioDetector result
        cusum     : CUSUMDetector result
        ewma      : EWMADetector result

    Returns:
        FusionResult with final score and explanation
    """
    named: list[Tuple[str, DetectorResult]] = [
        ("absolute", absolute),
        ("mad", mad),
        ("vol_ratio", vol_ratio),
        ("cusum", cusum),
        ("ewma", ewma),
    ]

    scores = {name: res.score for name, res in named}
    reasons = {name: res.reason for name, res in named}
    max_score = max(scores.values())
    max_name = max(scores, key=lambda k: scores[k])

    triggered = [name for name, res in named if res.triggered]
    triggered_count = len(triggered)

    # --- TIER 1: COINCIDENCE — 2+ detectors triggered ---
    if triggered_count >= 2:
        # Weighted average of triggered detectors only
        total_weight = sum(_WEIGHTS[n] for n in triggered)
        weighted_sum = sum(_WEIGHTS[n] * scores[n] for n in triggered)
        score = weighted_sum / total_weight if total_weight > 0 else max_score
        # Cap coincidence scores at 0.85 to prevent jumping to 1.0
        score = min(0.85, score)
        label = " + ".join(reasons[n] for n in triggered)
        return FusionResult(
            anomaly_score=score,
            reason=f"coincidence: {label}",
            triggered_count=triggered_count,
            max_detector_score=max_score,
            absolute_score=scores["absolute"],
            mad_score=scores["mad"],
            vol_ratio_score=scores["vol_ratio"],
            cusum_score=scores["cusum"],
            ewma_score=scores["ewma"],
        )

    # --- TIER 2: NORMAL — weighted average of all detectors ---
    total_weight = sum(_WEIGHTS.values())
    weighted_sum = sum(_WEIGHTS[name] * scores[name] for name in scores)
    score = weighted_sum / total_weight
    # Cap normal tier at 0.70 to leave headroom for coincidence/extreme
    score = min(0.70, score)

    if triggered_count == 1:
        reason = reasons[triggered[0]]
    elif max_score < 0.20:
        reason = "normal"
    else:
        reason = reasons[max_name]

    return FusionResult(
        anomaly_score=score,
        reason=reason,
        triggered_count=triggered_count,
        max_detector_score=max_score,
        absolute_score=scores["absolute"],
        mad_score=scores["mad"],
        vol_ratio_score=scores["vol_ratio"],
        cusum_score=scores["cusum"],
        ewma_score=scores["ewma"],
    )