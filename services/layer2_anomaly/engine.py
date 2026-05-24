"""Layer 2 anomaly scoring engine.

Builds rolling features, runs anomaly models, and drives the decision-gate state machine.
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Tuple

import numpy as np
from river.anomaly import HalfSpaceTrees
from sklearn.ensemble import IsolationForest


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def log_return(p_prev: float, p_cur: float) -> float:
    if p_prev <= 0.0 or p_cur <= 0.0:
        return 0.0
    return math.log(p_cur / p_prev)


@dataclass
class RollingFeatureWindow:
    """Maintains a fixed-size rolling window of raw feature values for z-scoring + MAD."""

    maxlen: int = 500

    _f1_rets: Deque[float] = None  # type: ignore[assignment]
    _f2_log_vol: Deque[float] = None  # type: ignore[assignment]
    _f3_spread: Deque[float] = None  # type: ignore[assignment]

    _sum_f1: float = 0.0
    _sumsq_f1: float = 0.0
    _sum_f2: float = 0.0
    _sumsq_f2: float = 0.0
    _sum_f3: float = 0.0
    _sumsq_f3: float = 0.0

    def __post_init__(self) -> None:
        self._f1_rets = deque(maxlen=self.maxlen)
        self._f2_log_vol = deque(maxlen=self.maxlen)
        self._f3_spread = deque(maxlen=self.maxlen)

    def _push(self, q: Deque[float], *, value: float, sum_name: str, sumsq_name: str) -> None:
        if len(q) == q.maxlen and q.maxlen is not None:
            old = q[0]
            setattr(self, sum_name, getattr(self, sum_name) - old)
            setattr(self, sumsq_name, getattr(self, sumsq_name) - old * old)
        q.append(value)
        setattr(self, sum_name, getattr(self, sum_name) + value)
        setattr(self, sumsq_name, getattr(self, sumsq_name) + value * value)

    def add(self, *, f1_ret: float, f2_log_vol: float, f3_spread: float) -> None:
        self._push(self._f1_rets, value=f1_ret, sum_name="_sum_f1", sumsq_name="_sumsq_f1")
        self._push(self._f2_log_vol, value=f2_log_vol, sum_name="_sum_f2", sumsq_name="_sumsq_f2")
        self._push(self._f3_spread, value=f3_spread, sum_name="_sum_f3", sumsq_name="_sumsq_f3")

    def _mean_std(self, *, n: int, s: float, ss: float) -> Tuple[float, float]:
        if n <= 1:
            return 0.0, 0.0
        mean = s / n
        var = max(0.0, (ss / n) - (mean * mean))
        return mean, math.sqrt(var)

    def stats_f1(self) -> Tuple[float, float]:
        return self._mean_std(n=len(self._f1_rets), s=self._sum_f1, ss=self._sumsq_f1)

    def stats_f2(self) -> Tuple[float, float]:
        return self._mean_std(n=len(self._f2_log_vol), s=self._sum_f2, ss=self._sumsq_f2)

    def stats_f3(self) -> Tuple[float, float]:
        return self._mean_std(n=len(self._f3_spread), s=self._sum_f3, ss=self._sumsq_f3)

    def mad_f1(self) -> float:
        xs = list(self._f1_rets)
        if len(xs) < 5:
            return 0.0
        med = statistics.median(xs)
        dev = [abs(x - med) for x in xs]
        return float(statistics.median(dev))


@dataclass
class RollingRV30m:
    window_ms: int = 30 * 60 * 1000
    _rets: Deque[Tuple[int, float]] = None  # type: ignore[assignment]
    _sum_sq: float = 0.0

    def __post_init__(self) -> None:
        self._rets = deque()

    def add(self, *, ts_ms: int, ret: float) -> float:
        self._rets.append((ts_ms, ret))
        self._sum_sq += ret * ret

        cutoff = ts_ms - self.window_ms
        while self._rets and self._rets[0][0] < cutoff:
            _, r0 = self._rets.popleft()
            self._sum_sq -= r0 * r0

        return math.sqrt(max(0.0, self._sum_sq))


@dataclass
class HMMRegime:
    regime: int
    posterior: List[float]


class HMMRegimeClassifier:
    def __init__(self, *, model_path: str, expected_states: int = 2, history_max: int = 500) -> None:
        import joblib

        self._model = joblib.load(model_path)
        self._expected_states = int(expected_states)
        self._history: Deque[float] = deque(maxlen=history_max)

    def update(self, *, rv_30m: float) -> HMMRegime:
        self._history.append(float(rv_30m))
        X = np.array(list(self._history), dtype=float).reshape(-1, 1)

        # predict() is Viterbi state sequence; predict_proba() gives posteriors.
        states = self._model.predict(X)
        post = self._model.predict_proba(X)

        regime = int(states[-1])
        posterior = [float(x) for x in post[-1].reshape(-1).tolist()]
        if len(posterior) != self._expected_states:
            raise RuntimeError(
                f"HMM posterior length {len(posterior)} does not match expected state count {self._expected_states}"
            )
        return HMMRegime(regime=regime, posterior=posterior)


class IsolationForestScorer:
    def __init__(
        self,
        *,
        n_estimators: int = 100,
        contamination: float = 0.01,
        max_samples: int = 256,
        retrain_interval_s: int = 15 * 60,
        warmup_min_samples: int = 256,
        seed: int = 42,
        max_training_buffer: int = 5000,
    ) -> None:
        self._cfg = dict(
            n_estimators=n_estimators,
            contamination=contamination,
            max_samples=max_samples,
            random_state=seed,
        )
        self._retrain_interval_s = retrain_interval_s
        self._warmup_min_samples = warmup_min_samples
        self._buf: Deque[np.ndarray] = deque(maxlen=max_training_buffer)

        self._lock = threading.Lock()
        self._model: Optional[IsolationForest] = None
        self._last_train_s = 0.0
        self._train_inflight = False

    def add_training_sample(self, vec: np.ndarray) -> None:
        self._buf.append(vec)

    def _train(self) -> None:
        try:
            X = np.stack(list(self._buf), axis=0)
            model = IsolationForest(**self._cfg)
            model.fit(X)
            with self._lock:
                self._model = model
                self._last_train_s = time.time()
        finally:
            self._train_inflight = False

    def maybe_retrain_async(self) -> None:
        now = time.time()
        if self._train_inflight:
            return
        if len(self._buf) < self._warmup_min_samples:
            return
        if self._model is not None and (now - self._last_train_s) < self._retrain_interval_s:
            return

        self._train_inflight = True
        threading.Thread(target=self._train, name="iforest-train", daemon=True).start()

    def score(self, vec: np.ndarray) -> float:
        """
        Compute anomaly score in [0, 1] range using sklearn's IsolationForest.
        
        sklearn's IsolationForest.decision_function() returns:
        - Negative values for anomalies (more negative = more anomalous)
        - Positive values for normal points (more positive = more normal)
        - Typical range: [-0.5, +0.5] (but can exceed this range)
        
        Conversion formula:
            anomaly_score = clamp(1.0 - (decision_function + 0.5), 0, 1)
        
        This mapping ensures:
            df = -0.5 (strong anomaly) → score = 1.0
            df =  0.0 (neutral)        → score = 0.5
            df = +0.5 (normal)         → score = 0.0
        
        The +0.5 offset centers the typical range at 0.5, and the
        1.0 - x inversion converts "more negative = anomaly" to
        "higher score = anomaly". The clamp ensures output stays in [0, 1].
        
        Reference: sklearn.ensemble.IsolationForest documentation
        https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html
        
        Args:
            vec: Feature vector (7 features: f1, f2, f3, regime, trust, tod_sin, tod_cos)
        
        Returns:
            Anomaly score in [0, 1] where 0=normal, 1=anomaly
        """
        with self._lock:
            model = self._model
        if model is None:
            return 0.0

        df = float(model.decision_function(vec.reshape(1, -1))[0])
        # Convert sklearn's decision_function to [0, 1] anomaly score
        return _clamp01(1.0 - (df + 0.5))


class HalfSpaceTreeScorer:
    def __init__(self) -> None:
        self._model = HalfSpaceTrees(n_trees=25, height=15, window_size=250, seed=42)

    def score_and_learn(self, features: Dict[str, float]) -> float:
        # Critical scoring order: score first, then learn.
        s = float(self._model.score_one(features))
        self._model.learn_one(features)
        return _clamp01(s)


@dataclass
class Layer2Scores:
    anomaly_score: float
    if_score: float
    hst_score: float
    mad_guard_triggered: bool
    regime: int
    regime_posterior: List[float]
    # Feature vector for observability
    feature_raw_return: float = 0.0
    feature_rolling_vol: float = 0.0
    feature_spread_z: float = 0.0
    feature_latency_z: float = 0.0  # Not yet implemented
    feature_volume_z: float = 0.0
    feature_trust_score: float = 0.0  # Renamed from feature_trust_degradation (was misleading)


class Layer2ScoringEngine:
    def __init__(
        self,
        *,
        hmm_model_path: str,
        if_weight: float = 0.45,
        hst_weight: float = 0.55,
        mad_floor: float = 0.65,
    ) -> None:
        self._feat = RollingFeatureWindow(maxlen=500)
        self._rv = RollingRV30m()
        self._hmm = HMMRegimeClassifier(model_path=hmm_model_path, expected_states=2)
        self._if = IsolationForestScorer()
        self._hst = HalfSpaceTreeScorer()

        self._if_weight = float(if_weight)
        self._hst_weight = float(hst_weight)
        self._mad_floor = float(mad_floor)

        self._prev_price: Optional[float] = None

    def score_tick(
        self,
        *,
        symbol: str,
        ts_ms: int,
        mid_price: float,
        trust_score: float,
        volume_24h: Optional[float],
        spread: Optional[float],
    ) -> Layer2Scores:
        if self._prev_price is None:
            self._prev_price = mid_price

        f1_raw = log_return(self._prev_price, mid_price)
        self._prev_price = mid_price

        f2_raw = math.log(max(1e-12, float(volume_24h or 0.0)))
        f3_raw = float(spread or 0.0)

        self._feat.add(f1_ret=f1_raw, f2_log_vol=f2_raw, f3_spread=f3_raw)

        rv_30m = self._rv.add(ts_ms=ts_ms, ret=f1_raw)
        regime = self._hmm.update(rv_30m=rv_30m)

        # Z-scoring for f1,f2,f3
        m1, s1 = self._feat.stats_f1()
        m2, s2 = self._feat.stats_f2()
        m3, s3 = self._feat.stats_f3()

        def z(x: float, m: float, s: float) -> float:
            if s <= 1e-12:
                return 0.0
            return (x - m) / s

        f1 = z(f1_raw, m1, s1)
        f2 = z(f2_raw, m2, s2)
        f3 = z(f3_raw, m3, s3)

        # Time of day features (UTC seconds modulo day)
        tod_s = int((ts_ms // 1000) % 86400)
        ang = 2.0 * math.pi * (tod_s / 86400.0)
        tod_sin = math.sin(ang)
        tod_cos = math.cos(ang)

        # Feature vector used for both IF and HST
        feat_dict = {
            "f1": float(f1),
            "f2": float(f2),
            "f3": float(f3),
            "regime": float(regime.regime),
            "trust": float(trust_score),
            "tod_sin": float(tod_sin),
            "tod_cos": float(tod_cos),
        }

        vec = np.array(
            [feat_dict["f1"], feat_dict["f2"], feat_dict["f3"], feat_dict["regime"], feat_dict["trust"], feat_dict["tod_sin"], feat_dict["tod_cos"]],
            dtype=float,
        )

        self._if.add_training_sample(vec)
        self._if.maybe_retrain_async()

        if_score = self._if.score(vec)
        hst_score = self._hst.score_and_learn(feat_dict)

        a_combined = (self._if_weight * if_score) + (self._hst_weight * hst_score)
        a_combined = _clamp01(a_combined)

        # MAD guard on raw return (2-state model: regime 0=low vol, regime 1=high vol)
        mad = self._feat.mad_f1()
        k = {0: 4.0, 1: 8.0}.get(regime.regime, 4.0)  # Low vol: stricter (4σ), High vol: lenient (8σ)
        mad_guard_triggered = bool(mad > 0.0 and abs(f1_raw) > (k * mad))

        if mad_guard_triggered:
            a_final = max(a_combined, self._mad_floor)
        else:
            a_final = a_combined

        return Layer2Scores(
            anomaly_score=float(_clamp01(a_final)),
            if_score=float(if_score),
            hst_score=float(hst_score),
            mad_guard_triggered=mad_guard_triggered,
            regime=int(regime.regime),
            regime_posterior=regime.posterior,
            feature_raw_return=float(f1_raw),
            feature_rolling_vol=float(rv_30m),
            feature_spread_z=float(f3),
            feature_latency_z=0.0,  # Not yet implemented
            feature_volume_z=float(f2),
            feature_trust_score=float(trust_score),  # Renamed from feature_trust_degradation
        )


class DecisionGate:
    _severity = {"NORMAL": 0, "CONSERVATIVE": 1, "DEGRADED": 2, "HALT": 3}

    def __init__(
        self,
        *,
        trust_threshold: float = 0.60,
        anomaly_threshold: float = 0.55,  # Match service.py default
        upgrade_streak_required: int = 10,
    ) -> None:
        self._trust_threshold = float(trust_threshold)
        self._anomaly_threshold = float(anomaly_threshold)
        self._upgrade_streak_required = int(upgrade_streak_required)

        self._state: str = "NORMAL"
        self._upgrade_target: Optional[str] = None
        self._upgrade_streak: int = 0

    @property
    def state(self) -> str:
        return self._state

    def _base_state(self, *, trust: float, anomaly: float) -> str:
        high_trust = trust >= self._trust_threshold
        high_anom = anomaly >= self._anomaly_threshold

        if high_trust and not high_anom:
            return "NORMAL"
        if high_trust and high_anom:
            return "CONSERVATIVE"
        if (not high_trust) and (not high_anom):
            return "DEGRADED"
        return "HALT"

    def update(self, *, trust: float, anomaly: float) -> str:
        base = self._base_state(trust=trust, anomaly=anomaly)

        # Downgrades are immediate, especially to HALT.
        if self._severity[base] > self._severity[self._state]:
            self._state = base
            self._upgrade_target = None
            self._upgrade_streak = 0
            return self._state

        # HALT requires 10 consecutive NORMAL-qualifying ticks to leave.
        if self._state == "HALT":
            if base == "NORMAL":
                self._upgrade_streak += 1
            else:
                self._upgrade_streak = 0
            if self._upgrade_streak >= self._upgrade_streak_required:
                self._state = "NORMAL"
                self._upgrade_streak = 0
            return self._state

        # Upgrades require consecutive qualifying ticks.
        if self._severity[base] < self._severity[self._state]:
            if self._upgrade_target != base:
                self._upgrade_target = base
                self._upgrade_streak = 1
            else:
                self._upgrade_streak += 1

            if self._upgrade_streak >= self._upgrade_streak_required:
                self._state = base
                self._upgrade_target = None
                self._upgrade_streak = 0
            return self._state

        # Same state.
        self._upgrade_target = None
        self._upgrade_streak = 0
        self._state = base
        return self._state
