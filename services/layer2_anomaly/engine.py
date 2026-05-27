"""Layer 2 Scoring Engine.

Orchestrates:
  1. HMM regime classifier  — provides regime context (0=low vol, 1=high vol)
  2. Detector suite         — five specialized detectors
  3. Fusion layer           — combines scores with coincidence check
  4. Decision Gate          — 4-state machine with hysteresis

HMM feeds the Decision Gate as a threshold modifier, NOT the detectors.
Detectors are regime-agnostic; the gate tightens/loosens based on regime.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

import numpy as np

from .detectors import (
    AbsoluteThresholdDetector,
    CUSUMDetector,
    DetectorResult,
    EWMADetector,
    MADDetector,
    VolatilityRatioDetector,
)
from .fusion import FusionResult, fuse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def log_return(p_prev: float, p_cur: float) -> float:
    if p_prev <= 0.0 or p_cur <= 0.0:
        return 0.0
    return math.log(p_cur / p_prev)


# ---------------------------------------------------------------------------
# Rolling 30-minute Realized Volatility
# ---------------------------------------------------------------------------

@dataclass
class RollingRV30m:
    window_ms: int = 30 * 60 * 1000
    _rets: Deque[Tuple[int, float]] = field(default_factory=deque, init=False, repr=False)
    _sum_sq: float = field(default=0.0, init=False, repr=False)

    def add(self, *, ts_ms: int, ret: float) -> float:
        self._rets.append((ts_ms, ret))
        self._sum_sq += ret * ret
        cutoff = ts_ms - self.window_ms
        while self._rets and self._rets[0][0] < cutoff:
            _, r0 = self._rets.popleft()
            self._sum_sq -= r0 * r0
        return math.sqrt(max(0.0, self._sum_sq))


# ---------------------------------------------------------------------------
# HMM Regime Classifier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HMMRegime:
    regime: int            # 0 = low vol, 1 = high vol
    posterior: List[float] # [p0, p1], sums to 1.0


class HMMRegimeClassifier:
    """Loads a pre-trained 2-state GaussianHMM and emits regime labels.

    Uses a sliding window of the last 30 RV samples for Viterbi inference
    to avoid O(n²) cost from growing history.
    """

    def __init__(
        self,
        *,
        model_path: str,
        history_max: int = 500,
        inference_window: int = 30,
    ) -> None:
        import joblib
        self._model = joblib.load(model_path)
        self._history: Deque[float] = deque(maxlen=history_max)
        self._inference_window = inference_window
        self._last_regime = HMMRegime(regime=0, posterior=[1.0, 0.0])

    def update(self, *, rv_30m: float) -> HMMRegime:
        self._history.append(float(rv_30m))
        window = list(self._history)[-self._inference_window:]
        X = np.array(window, dtype=float).reshape(-1, 1)
        states = self._model.predict(X)
        post = self._model.predict_proba(X)[-1]
        regime = HMMRegime(
            regime=int(states[-1]),
            posterior=[float(p) for p in post.tolist()],
        )
        self._last_regime = regime
        return regime


# ---------------------------------------------------------------------------
# Decision Gate (4-state machine with hysteresis)
# ---------------------------------------------------------------------------

class DecisionGate:
    """Routes anomaly scores to control logic with regime-adaptive thresholds.

    States (ascending severity):
        NORMAL → CONSERVATIVE → DEGRADED → HALT

    Transitions:
        Downgrade : immediate (1 tick)
        Upgrade   : requires `upgrade_streak_required` consecutive ticks
        HALT exit : requires `upgrade_streak_required` consecutive NORMAL ticks

    Regime modulation:
        Regime 0 (low vol)  → anomaly threshold tightened by `regime_adj`
        Regime 1 (high vol) → anomaly threshold loosened by `regime_adj`
    """

    _SEVERITY = {"NORMAL": 0, "CONSERVATIVE": 1, "DEGRADED": 2, "HALT": 3}

    def __init__(
        self,
        *,
        trust_threshold: float = 0.60,
        anomaly_threshold: float = 0.55,
        upgrade_streak_required: int = 10,
        regime_adj: float = 0.10,
    ) -> None:
        self._trust_thr = trust_threshold
        self._anomaly_thr = anomaly_threshold
        self._streak_required = upgrade_streak_required
        self._regime_adj = regime_adj

        self._state = "NORMAL"
        self._upgrade_target: Optional[str] = None
        self._upgrade_streak = 0

    @property
    def state(self) -> str:
        return self._state

    def _base_state(self, *, trust: float, anomaly: float, regime: int) -> str:
        high_trust = trust >= self._trust_thr
        if regime == 0:
            anom_thr = self._anomaly_thr - self._regime_adj  # stricter
        else:
            anom_thr = self._anomaly_thr + self._regime_adj  # looser
        high_anom = anomaly >= anom_thr

        if high_trust and not high_anom:
            return "NORMAL"
        if high_trust and high_anom:
            return "CONSERVATIVE"
        if not high_trust and not high_anom:
            return "DEGRADED"
        return "HALT"  # low trust + high anomaly

    def update(self, *, trust: float, anomaly: float, regime: int) -> str:
        base = self._base_state(trust=trust, anomaly=anomaly, regime=regime)
        sev = self._SEVERITY

        # Immediate downgrade
        if sev[base] > sev[self._state]:
            self._state = base
            self._upgrade_target = None
            self._upgrade_streak = 0
            return self._state

        # HALT escape requires streak of NORMAL-qualifying ticks
        if self._state == "HALT":
            if base == "NORMAL":
                self._upgrade_streak += 1
            else:
                self._upgrade_streak = 0
            if self._upgrade_streak >= self._streak_required:
                self._state = "NORMAL"
                self._upgrade_streak = 0
            return self._state

        # Upgrades require streak
        if sev[base] < sev[self._state]:
            if self._upgrade_target != base:
                self._upgrade_target = base
                self._upgrade_streak = 1
            else:
                self._upgrade_streak += 1
            if self._upgrade_streak >= self._streak_required:
                self._state = base
                self._upgrade_target = None
                self._upgrade_streak = 0
            return self._state

        # Same severity
        self._upgrade_target = None
        self._upgrade_streak = 0
        self._state = base
        return self._state


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class Layer2Scores:
    # Final outputs
    anomaly_score: float
    system_state: str
    reason: str
    regime: int
    regime_posterior: List[float]

    # Individual detector scores (for observability / Prometheus)
    absolute_score: float
    mad_score: float
    vol_ratio_score: float
    cusum_score: float
    ewma_score: float

    # Fusion metadata
    triggered_count: int
    max_detector_score: float

    # Raw features (for observability)
    feature_return: float
    feature_rv30m: float
    feature_spread_bps: float
    feature_volume_ratio: float
    feature_price_jump_bps: float


# ---------------------------------------------------------------------------
# Main Engine
# ---------------------------------------------------------------------------

class Layer2ScoringEngine:
    """Per-symbol scoring engine.

    One instance per symbol, created on-demand by the service.
    All state is isolated — no cross-symbol contamination.
    """

    def __init__(
        self,
        *,
        symbol: str,
        hmm_model_path: str,
        # Detector tuning (all optional, defaults are sensible for crypto)
        abs_price_jump_bps: float = 100.0,
        abs_spread_bps: float = 50.0,
        abs_volume_spike_x: float = 10.0,
        mad_window: int = 100,
        mad_k_low: float = 4.0,
        mad_k_high: float = 8.0,
        vol_short_window: int = 30,
        vol_long_window: int = 300,
        vol_spike_ratio: float = 2.0,
        cusum_threshold: float = 5.0,
        cusum_drift: float = 0.5,
        ewma_lambda: float = 0.2,
        ewma_L: float = 3.0,
        # Gate tuning
        gate_trust_threshold: float = 0.60,
        gate_anomaly_threshold: float = 0.55,
        gate_upgrade_streak: int = 10,
        gate_regime_adj: float = 0.10,
        # Memory window tuning
        anomaly_memory_window: int = 30,
    ) -> None:
        self._symbol = symbol

        # --- Shared state ---
        self._rv = RollingRV30m()
        self._hmm = HMMRegimeClassifier(model_path=hmm_model_path)
        self._prev_price: Optional[float] = None

        # --- Detectors ---
        self._absolute = AbsoluteThresholdDetector(
            price_jump_bps=abs_price_jump_bps,
            spread_bps=abs_spread_bps,
            volume_spike_x=abs_volume_spike_x,
        )
        self._mad = MADDetector(
            window=mad_window,
            k_low_vol=mad_k_low,
            k_high_vol=mad_k_high,
        )
        self._vol_ratio = VolatilityRatioDetector(
            short_window=vol_short_window,
            long_window=vol_long_window,
            spike_ratio=vol_spike_ratio,
        )
        self._cusum = CUSUMDetector(
            threshold_sigma=cusum_threshold,
            drift=cusum_drift,
        )
        self._ewma = EWMADetector(
            lambda_=ewma_lambda,
            L=ewma_L,
        )

        # --- Decision Gate ---
        self._gate = DecisionGate(
            trust_threshold=gate_trust_threshold,
            anomaly_threshold=gate_anomaly_threshold,
            upgrade_streak_required=gate_upgrade_streak,
            regime_adj=gate_regime_adj,
        )

        # --- Rolling volume average for volume ratio feature ---
        self._vol_buf: Deque[float] = deque(maxlen=300)
        self._vol_sum: float = 0.0

        # --- Anomaly score memory window (default 30 ticks ≈ 30 seconds persistence) ---
        self._score_memory: Deque[float] = deque(maxlen=anomaly_memory_window)

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

    @property
    def gate_state(self) -> str:
        return self._gate.state

    def score_tick(
        self,
        *,
        ts_ms: int,
        mid_price: float,
        trust_score: float,
        volume_24h: Optional[float],
        spread: Optional[float],
    ) -> Layer2Scores:
        """Score one validated tick and return Layer2Scores.

        Args:
            ts_ms       : tick timestamp in milliseconds UTC
            mid_price   : mid-price of the instrument
            trust_score : Layer 1 trust score [0, 1]
            volume_24h  : 24h volume (any unit, consistent across ticks)
            spread      : bid-ask spread in price units

        Returns:
            Layer2Scores with anomaly_score, system_state, reasons, etc.
        """
        # --- Raw feature extraction ---
        prev = self._prev_price if self._prev_price is not None else mid_price
        if self._prev_price is None:
            self._prev_price = mid_price

        ret = log_return(prev, mid_price)
        price_jump_bps = ((mid_price - prev) / prev * 10_000) if prev > 0 else 0.0
        self._prev_price = mid_price

        volume = float(volume_24h or 0.0)
        spread_abs = float(spread or 0.0)
        spread_bps = (spread_abs / mid_price * 10_000) if mid_price > 0 else 0.0

        vol_avg = self._vol_avg()
        self._update_vol(volume)
        volume_ratio = (volume / vol_avg) if vol_avg > 0 else 1.0

        # --- Regime ---
        rv_30m = self._rv.add(ts_ms=ts_ms, ret=ret)
        regime = self._hmm.update(rv_30m=rv_30m)

        # --- Run detectors ---
        abs_result = self._absolute.update(
            price_jump_bps=price_jump_bps,
            spread_bps=spread_bps,
            volume=volume,
        )
        mad_result = self._mad.update(ret=ret, regime=regime.regime)
        vol_result = self._vol_ratio.update(ret=ret)
        cusum_result = self._cusum.update(
            price_jump_bps=price_jump_bps,
            spread_bps=spread_bps,
            volume=volume,
        )
        ewma_result = self._ewma.update(
            price_jump_bps=price_jump_bps,
            spread_bps=spread_bps,
        )

        # --- Fuse ---
        fusion: FusionResult = fuse(
            absolute=abs_result,
            mad=mad_result,
            vol_ratio=vol_result,
            cusum=cusum_result,
            ewma=ewma_result,
        )

        # --- Apply memory window for score persistence ---
        self._score_memory.append(fusion.anomaly_score)
        final_anomaly_score = max(self._score_memory) if self._score_memory else fusion.anomaly_score

        # --- Decision Gate (regime shifts thresholds, not scores) ---
        state = self._gate.update(
            trust=trust_score,
            anomaly=final_anomaly_score,
            regime=regime.regime,
        )

        return Layer2Scores(
            anomaly_score=final_anomaly_score,
            system_state=state,
            reason=fusion.reason,
            regime=regime.regime,
            regime_posterior=regime.posterior,
            absolute_score=fusion.absolute_score,
            mad_score=fusion.mad_score,
            vol_ratio_score=fusion.vol_ratio_score,
            cusum_score=fusion.cusum_score,
            ewma_score=fusion.ewma_score,
            triggered_count=fusion.triggered_count,
            max_detector_score=fusion.max_detector_score,
            feature_return=ret,
            feature_rv30m=rv_30m,
            feature_spread_bps=spread_bps,
            feature_volume_ratio=volume_ratio,
            feature_price_jump_bps=price_jump_bps,
        )