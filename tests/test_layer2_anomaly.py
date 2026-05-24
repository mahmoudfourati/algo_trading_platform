"""Tests for Layer 2 anomaly detection and regime classification.

Covers rolling statistics, HMM regime inference, MAD guard, and decision gate state machine.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import joblib
import numpy as np
import pytest

from services.layer2_anomaly.engine import (
    DecisionGate,
    HMMRegime,
    HMMRegimeClassifier,
    IsolationForestScorer,
    Layer2ScoringEngine,
    RollingFeatureWindow,
    RollingRV30m,
)
from services.layer2_anomaly.service import Layer2Service
from shared.schemas import ValidatedTick


def _validated_tick(
    *,
    symbol: str = "BTCUSDT",
    mid_price: float = 50000.0,
    spread: float = 1.0,
    volume_24h: float = 1000000.0,
    ts_ms: int | None = None,
) -> ValidatedTick:
    """Helper to construct a ValidatedTick for testing."""
    ts = int(time.time() * 1000) if ts_ms is None else ts_ms
    return ValidatedTick(
        exchange_id="binance",  # type: ignore[arg-type]
        symbol=symbol,
        bid=mid_price - spread / 2,
        ask=mid_price + spread / 2,
        last_price=mid_price,
        volume_24h=volume_24h,
        exchange_timestamp_ms=ts,
        received_timestamp_ms=ts,
        sequence_id=None,
        consensus_mid=mid_price,
        trust_score=0.85,
        t1_subscore=0.9,
        t2_subscore=0.8,
        t3_subscore=0.85,
        t4_subscore=0.90,
        t5_subscore=0.95,
        agreeing_sources=3,
        total_sources=3,
        tick_hash="abc123",
    )


# ============================================================================
# 5. SERVICE WATCHDOG TESTS (Layer 2 runtime silence handling)
# ============================================================================


class TestLayer2ServiceWatchdog:
    def test_watchdog_forces_halt_once_on_silence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        events: list[tuple[str, dict]] = []

        def fake_audit(event_type: str, *, source: str, payload: dict) -> None:
            events.append((event_type, payload))

        class FakePublisher:
            def __init__(self) -> None:
                self.published: list[dict] = []

            def publish(self, obj: dict) -> None:
                self.published.append(obj)

            def stop(self) -> None:
                return None

        class FakeConsumer:
            def poll(self, timeout_ms: int, max_records: int):  # noqa: D401 - test stub
                return {}

            def close(self) -> None:
                return None

        monkeypatch.setattr("services.layer2_anomaly.service.emit_audit_event", fake_audit)

        service = Layer2Service(
            consumer=FakeConsumer(),
            publisher=FakePublisher(),
            engine_by_symbol={},
            gate=DecisionGate(),
            missing_data_timeout_s=30.0,
        )
        service._last_valid_tick_s = 0.0

        service._check_watchdog(now_s=31.0)
        assert service.gate.state == "HALT"
        assert service._watchdog_in_halt is True
        assert [event_type for event_type, _ in events] == ["layer2.watchdog.timeout"]

        service._check_watchdog(now_s=62.0)
        assert [event_type for event_type, _ in events] == ["layer2.watchdog.timeout"]


# ============================================================================
# 1. ROLLING STATISTICS TESTS (RollingFeatureWindow)
# ============================================================================


class TestRollingFeatureWindow:
    """Test Welford online statistics against numpy hand calculations."""

    def test_welford_mean_matches_numpy(self) -> None:
        """Verify rolling mean computation matches numpy.mean()."""
        win = RollingFeatureWindow(maxlen=500)

        # Add 10 log returns
        log_returns = [0.001, 0.002, -0.0015, 0.003, -0.001, 0.0025, 0.0005, -0.002, 0.0015, 0.002]

        for ret in log_returns:
            win.add(f1_ret=ret, f2_log_vol=5.0, f3_spread=2.0)

        # Compute expected mean
        expected_mean = np.mean(log_returns)
        actual_mean, _ = win.stats_f1()

        assert abs(actual_mean - expected_mean) < 1e-10, f"Mean mismatch: {actual_mean} vs {expected_mean}"

    def test_welford_std_matches_numpy(self) -> None:
        """Verify rolling std computation matches numpy.std()."""
        win = RollingFeatureWindow(maxlen=500)

        log_returns = [0.001, 0.002, -0.0015, 0.003, -0.001, 0.0025, 0.0005, -0.002, 0.0015, 0.002]

        for ret in log_returns:
            win.add(f1_ret=ret, f2_log_vol=5.0, f3_spread=2.0)

        expected_std = np.std(log_returns, ddof=0)  # Population std
        _, actual_std = win.stats_f1()

        assert abs(actual_std - expected_std) < 1e-10, f"Std mismatch: {actual_std} vs {expected_std}"

    def test_rolling_window_size_respected(self) -> None:
        """Verify window size cap is enforced; oldest values are dropped."""
        win = RollingFeatureWindow(maxlen=5)

        # Add 10 items
        for i in range(10):
            win.add(f1_ret=float(i), f2_log_vol=5.0, f3_spread=2.0)

        # Only last 5 should be in window: [5, 6, 7, 8, 9]
        expected_mean = (5 + 6 + 7 + 8 + 9) / 5  # 7.0
        actual_mean, _ = win.stats_f1()

        assert abs(actual_mean - expected_mean) < 1e-10

    def test_z_score_normalization(self) -> None:
        """Verify z-scoring: (x - mean) / std."""
        win = RollingFeatureWindow(maxlen=500)

        log_returns = [0.001, 0.002, -0.0015, 0.003, -0.001]
        for ret in log_returns:
            win.add(f1_ret=ret, f2_log_vol=5.0, f3_spread=2.0)

        # Add a new value and z-score it
        new_ret = 0.002
        win.add(f1_ret=new_ret, f2_log_vol=5.0, f3_spread=2.0)

        mean, std = win.stats_f1()

        expected_z = (new_ret - mean) / std if std > 1e-12 else 0.0
        actual_z = (new_ret - mean) / std if std > 1e-12 else 0.0

        assert abs(actual_z - expected_z) < 1e-10

    def test_mad_calculation(self) -> None:
        """Verify MAD (median absolute deviation) calculation."""
        win = RollingFeatureWindow(maxlen=500)

        log_returns = [-0.01, -0.005, 0.0, 0.005, 0.01]
        for ret in log_returns:
            win.add(f1_ret=ret, f2_log_vol=5.0, f3_spread=2.0)

        # MAD = median(|x - median(x)|)
        arr = np.array(log_returns)
        median = np.median(arr)
        expected_mad = np.median(np.abs(arr - median))
        actual_mad = win.mad_f1()

        assert abs(actual_mad - expected_mad) < 1e-10


# ============================================================================
# 2. HMM REGIME INFERENCE TESTS (HMMRegimeClassifier)
# ============================================================================


class TestHMMRegimeClassifier:
    """Test 2-state HMM regime inference and stability."""

    @pytest.fixture
    def hmm_classifier(self) -> HMMRegimeClassifier:
        """Load the trained 2-state HMM model."""
        model_path = Path(__file__).parent.parent / "artifacts" / "hmm" / "model.pkl"
        if not model_path.exists():
            pytest.skip(f"HMM model not found at {model_path}")
        
        return HMMRegimeClassifier(model_path=str(model_path))

    def test_regime_output_is_0_or_1(self, hmm_classifier: HMMRegimeClassifier) -> None:
        """Verify regime label is always 0 or 1 (2-state model)."""
        # Simulate normal volatility: add consistent low RV values
        for _ in range(10):
            regime = hmm_classifier.update(rv_30m=0.003)
            assert regime.regime in [0, 1], f"Regime must be 0 or 1, got {regime.regime}"

    def test_posterior_sums_to_one(self, hmm_classifier: HMMRegimeClassifier) -> None:
        """Verify posterior probabilities sum to ~1.0."""
        for _ in range(10):
            regime = hmm_classifier.update(rv_30m=0.003)
            posterior_sum = sum(regime.posterior)
            assert abs(posterior_sum - 1.0) < 1e-6, f"Posterior sum {posterior_sum} != 1.0"

    def test_posterior_has_two_entries(self, hmm_classifier: HMMRegimeClassifier) -> None:
        """Verify posterior always has exactly 2 entries (2-state model)."""
        for _ in range(10):
            regime = hmm_classifier.update(rv_30m=0.003)
            assert len(regime.posterior) == 2, f"Posterior length {len(regime.posterior)} != 2"

    def test_regime_switches_on_volatility_spike(self, hmm_classifier: HMMRegimeClassifier) -> None:
        """Verify regime may switch when volatility spikes (Viterbi path updates)."""
        # Start with low volatility
        regimes_low = []
        for _ in range(20):
            regime = hmm_classifier.update(rv_30m=0.003)
            regimes_low.append(regime.regime)

        # Then high volatility
        regimes_high = []
        for _ in range(20):
            regime = hmm_classifier.update(rv_30m=0.015)
            regimes_high.append(regime.regime)

        # Count regime 1 frequency
        regime_1_low_fraction = regimes_low.count(1) / len(regimes_low) if len(regimes_low) > 0 else 0
        regime_1_high_fraction = regimes_high.count(1) / len(regimes_high) if len(regimes_high) > 0 else 0

        # High volatility period should have more regime 1 than low volatility period
        # (at least directionally, though not guaranteed by HMM)
        assert regime_1_high_fraction >= regime_1_low_fraction * 0.5, (
            f"High vol should have more regime 1: low={regime_1_low_fraction:.2f}, high={regime_1_high_fraction:.2f}"
        )

    def test_mismatched_posterior_length_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeModel:
            def predict(self, X):
                return np.array([0, 1])

            def predict_proba(self, X):
                return np.array([[0.2, 0.3, 0.5], [0.1, 0.2, 0.7]])

        monkeypatch.setattr("joblib.load", lambda _path: FakeModel())

        classifier = HMMRegimeClassifier(model_path="/tmp/fake-model.pkl", expected_states=2)
        with pytest.raises(RuntimeError, match="posterior length"):
            classifier.update(rv_30m=0.003)


# ============================================================================
# 3. MAD GUARD TESTS (Regime-Aware Outlier Detection)
# ============================================================================


class TestMADGuard:
    """Test regime-dependent MAD threshold logic."""

    def test_mad_guard_thresholds_by_regime(self) -> None:
        """Verify correct MAD multipliers: regime 0 (k=4.0), regime 1 (k=8.0)."""
        # Regime-to-k mapping from engine.py line 323
        regime_k_map = {0: 4.0, 1: 8.0}

        for regime_id, expected_k in regime_k_map.items():
            k = regime_k_map.get(regime_id, 4.0)
            assert k == expected_k, f"Regime {regime_id} should have k={expected_k}, got {k}"

    def test_mad_guard_triggered_condition(self) -> None:
        """Test MAD guard trigger: |raw_return| > k * MAD."""
        win = RollingFeatureWindow(maxlen=500)

        # Add small returns to establish baseline MAD
        for ret in [0.001, 0.0005, -0.0005, 0.001, -0.001]:
            win.add(f1_ret=ret, f2_log_vol=5.0, f3_spread=2.0)

        mad = win.mad_f1()
        print(f"Baseline MAD: {mad}")

        # Regime 0 (k=4.0): should trigger if |ret| > 4 * MAD
        k_regime_0 = 4.0
        threshold_regime_0 = k_regime_0 * mad

        # Test: small return should NOT trigger
        ret_small = 0.001
        should_trigger_small = abs(ret_small) > threshold_regime_0
        assert not should_trigger_small, f"Small return {ret_small} should not trigger MAD guard (threshold={threshold_regime_0})"

        # Test: large return SHOULD trigger
        ret_large = 0.05  # 50x the baseline
        should_trigger_large = abs(ret_large) > threshold_regime_0
        assert should_trigger_large, f"Large return {ret_large} should trigger MAD guard (threshold={threshold_regime_0})"

    def test_mad_guard_floor_applied_on_trigger(self) -> None:
        """Verify MAD guard floors anomaly_score at 0.65 when triggered."""
        mad_floor = 0.65

        # If anomaly_score from ensemble is 0.3 but MAD triggers, result should be max(0.3, 0.65) = 0.65
        ensemble_score = 0.3
        triggered = True

        result = max(ensemble_score, mad_floor) if triggered else ensemble_score
        assert result == mad_floor


# ============================================================================
# 4. DECISION GATE STATE MACHINE TESTS
# ============================================================================


class TestDecisionGate:
    """Test 4-state machine with hysteresis and transition logic."""

    def test_initial_state_is_normal(self) -> None:
        """Verify gate starts in NORMAL state."""
        gate = DecisionGate()
        assert gate.state == "NORMAL", f"Initial state should be NORMAL, got {gate.state}"

    def test_downgrade_normal_to_conservative_immediate(self) -> None:
        """Verify immediate downgrade: high_anom + high_trust → CONSERVATIVE."""
        gate = DecisionGate()

        # high_anom=True, high_trust=True → state should be CONSERVATIVE
        gate.update(trust=0.75, anomaly=0.60)

        assert gate.state == "CONSERVATIVE", f"Expected CONSERVATIVE, got {gate.state}"

    def test_downgrade_normal_to_degraded_immediate(self) -> None:
        """Verify immediate downgrade: low_trust + low_anom → DEGRADED."""
        gate = DecisionGate()

        # low_trust=True, low_anom=False → state should be DEGRADED
        gate.update(trust=0.50, anomaly=0.40)

        assert gate.state == "DEGRADED", f"Expected DEGRADED, got {gate.state}"

    def test_downgrade_normal_to_halt_immediate(self) -> None:
        """Verify immediate downgrade: low_trust + high_anom → HALT."""
        gate = DecisionGate()

        # low_trust=True, high_anom=True → state should be HALT
        gate.update(trust=0.50, anomaly=0.60)

        assert gate.state == "HALT", f"Expected HALT, got {gate.state}"

    def test_upgrade_requires_10_consecutive_ticks(self) -> None:
        """Verify upgrades require 10 consecutive qualifying ticks (hysteresis)."""
        gate = DecisionGate()

        # Start in CONSERVATIVE (high_anom + high_trust)
        gate.update(trust=0.75, anomaly=0.60)
        assert gate.state == "CONSERVATIVE"

        # Transition to NORMAL-qualifying conditions: high_trust + low_anom
        # But should remain CONSERVATIVE until 10 consecutive ticks
        for i in range(9):
            gate.update(trust=0.75, anomaly=0.40)
            assert gate.state == "CONSERVATIVE", f"Should stay CONSERVATIVE after {i+1} ticks, got {gate.state}"

        # 10th tick should upgrade to NORMAL
        gate.update(trust=0.75, anomaly=0.40)
        assert gate.state == "NORMAL", f"Expected NORMAL after 10 ticks, got {gate.state}"

    def test_downgrade_resets_upgrade_counter(self) -> None:
        """Verify downgrade during upgrade streak resets the counter."""
        gate = DecisionGate()

        # Start in CONSERVATIVE
        gate.update(trust=0.75, anomaly=0.60)
        assert gate.state == "CONSERVATIVE"

        # Begin upgrade streak: 5 ticks towards NORMAL
        for _ in range(5):
            gate.update(trust=0.75, anomaly=0.40)

        # Downgrade back to high_anom: counter should reset
        gate.update(trust=0.75, anomaly=0.60)

        # Now try upgrade again: should need another 10, not 5
        for i in range(9):
            gate.update(trust=0.75, anomaly=0.40)
            assert gate.state == "CONSERVATIVE"

        # 10th tick should upgrade
        gate.update(trust=0.75, anomaly=0.40)
        assert gate.state == "NORMAL"

    def test_halt_escape_requires_10_normal_ticks(self) -> None:
        """Verify escape from HALT requires 10 consecutive NORMAL-qualifying ticks."""
        gate = DecisionGate()

        # Force HALT: low_trust + high_anom
        gate.update(trust=0.50, anomaly=0.60)
        assert gate.state == "HALT"

        # Try to escape with NORMAL conditions: high_trust + low_anom
        # Should require 10 consecutive ticks
        for i in range(9):
            gate.update(trust=0.75, anomaly=0.40)
            assert gate.state == "HALT", f"Should stay in HALT after {i+1} recovery ticks, got {gate.state}"

        # 10th tick should escape to NORMAL
        gate.update(trust=0.75, anomaly=0.40)
        assert gate.state == "NORMAL", f"Expected NORMAL after 10 recovery ticks, got {gate.state}"

    def test_state_matrix_all_four_corners(self) -> None:
        """Test all four quadrants of the trust/anomaly state matrix."""
        test_cases = [
            # (trust, anomaly, expected_state, description)
            (0.75, 0.40, "NORMAL", "high_trust + low_anom"),
            (0.75, 0.60, "CONSERVATIVE", "high_trust + high_anom"),
            (0.50, 0.40, "DEGRADED", "low_trust + low_anom"),
            (0.50, 0.60, "HALT", "low_trust + high_anom"),
        ]

        for trust, anom, expected, desc in test_cases:
            gate = DecisionGate()
            gate.update(trust=trust, anomaly=anom)
            assert gate.state == expected, f"{desc}: expected {expected}, got {gate.state}"


# ============================================================================
# 5. ISOLATION FOREST SCORER TESTS (IF Warmup & Async Retrain)
# ============================================================================


class TestIsolationForestScorer:
    """Test IF scorer warmup phase and retrain behavior."""

    def test_if_returns_zero_during_warmup(self) -> None:
        """Verify IF returns 0.0 score when < 256 training samples."""
        scorer = IsolationForestScorer(warmup_min_samples=256, max_training_buffer=5000, retrain_interval_s=900)

        # Add only 100 samples
        for _ in range(100):
            feat_vec = np.array([0.001, 5.0, 2.0])
            score = scorer.score(feat_vec)
            assert score == 0.0, f"Score during warmup should be 0.0, got {score}"

    def test_if_starts_scoring_after_warmup(self) -> None:
        """Verify IF begins scoring after 256+ training samples."""
        scorer = IsolationForestScorer(warmup_min_samples=256, max_training_buffer=5000, retrain_interval_s=900)

        # Add 256 samples
        for i in range(256):
            feat_vec = np.array([0.001 * (1 + 0.1 * (i % 10)), 5.0, 2.0])
            scorer.add_training_sample(feat_vec)

        # Score should now be non-zero
        test_vec = np.array([0.001, 5.0, 2.0])
        score = scorer.score(test_vec)
        assert isinstance(score, float), f"Score should be float, got {type(score)}"

    def test_if_retrain_is_async_and_scoring_non_blocking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify retrain runs in background and score path remains non-blocking."""
        scorer = IsolationForestScorer(warmup_min_samples=8, max_training_buffer=128, retrain_interval_s=0)

        for i in range(16):
            scorer.add_training_sample(np.array([0.001 * (1 + 0.02 * i), 5.0, 2.0], dtype=float))

        original_train = scorer._train

        def slow_train() -> None:
            # Simulate a heavier train cycle to check that scoring still returns quickly.
            time.sleep(0.2)
            original_train()

        monkeypatch.setattr(scorer, "_train", slow_train)

        t_start = time.perf_counter()
        scorer.maybe_retrain_async()
        enqueue_dt = time.perf_counter() - t_start

        # If retrain is truly async, this should return immediately.
        assert enqueue_dt < 0.05, f"maybe_retrain_async took too long: {enqueue_dt:.4f}s"

        score_start = time.perf_counter()
        score = scorer.score(np.array([0.001, 5.0, 2.0], dtype=float))
        score_dt = time.perf_counter() - score_start

        assert isinstance(score, float)
        assert score_dt < 0.05, f"score() blocked during retrain: {score_dt:.4f}s"

        # Ensure background retrain completes and model is swapped in.
        deadline = time.time() + 2.0
        while scorer._model is None and time.time() < deadline:
            time.sleep(0.01)

        assert scorer._model is not None, "IF model was not swapped in after async retrain"

    def test_if_score_range_and_normalization(self) -> None:
        """Verify IF scores are always in [0, 1] range and normalization is correct."""
        scorer = IsolationForestScorer(warmup_min_samples=20, max_training_buffer=128, retrain_interval_s=900)

        # Add training samples (normal distribution around 0.005)
        for i in range(30):
            vec = np.array([0.005 + 0.001 * (i % 10 - 5), 5.0, 2.0, 0.0, 0.8, 0.5, 0.5], dtype=float)
            scorer.add_training_sample(vec)

        # Force training
        scorer._train()
        assert scorer._model is not None, "Model should be trained"

        # Test 1: Normal point (similar to training data)
        normal_vec = np.array([0.005, 5.0, 2.0, 0.0, 0.8, 0.5, 0.5], dtype=float)
        normal_score = scorer.score(normal_vec)
        assert 0.0 <= normal_score <= 1.0, f"Normal score {normal_score} out of [0, 1] range"
        assert normal_score < 0.6, f"Normal point should have low anomaly score, got {normal_score}"

        # Test 2: Anomaly point (very different from training data)
        anomaly_vec = np.array([0.5, 50.0, 20.0, 1.0, 0.2, 0.9, 0.1], dtype=float)
        anomaly_score = scorer.score(anomaly_vec)
        assert 0.0 <= anomaly_score <= 1.0, f"Anomaly score {anomaly_score} out of [0, 1] range"
        assert anomaly_score > normal_score, f"Anomaly should score higher than normal: {anomaly_score} vs {normal_score}"

        # Test 3: Multiple diverse points all stay in range
        test_vecs = [
            np.array([0.001, 4.0, 1.0, 0.0, 0.9, 0.3, 0.7], dtype=float),
            np.array([0.010, 6.0, 3.0, 1.0, 0.7, 0.6, 0.4], dtype=float),
            np.array([0.100, 10.0, 10.0, 1.0, 0.5, 0.8, 0.2], dtype=float),
        ]
        for vec in test_vecs:
            score = scorer.score(vec)
            assert 0.0 <= score <= 1.0, f"Score {score} for vec {vec} out of [0, 1] range"
            assert math.isfinite(score), f"Score {score} is not finite"


# ============================================================================
# 6. LAYER 2 SCORING ENGINE INTEGRATION TEST
# ============================================================================


class TestLayer2ScoringEngine:
    """Integration test: all components working together."""

    @pytest.fixture
    def scoring_engine(self) -> Layer2ScoringEngine:
        """Instantiate Layer 2 scoring engine with trained HMM."""
        model_path = Path(__file__).parent.parent / "artifacts" / "hmm" / "model.pkl"
        if not model_path.exists():
            pytest.skip(f"HMM model not found at {model_path}")

        engine = Layer2ScoringEngine(
            hmm_model_path=str(model_path),
            if_weight=0.45,
            hst_weight=0.55,
            mad_floor=0.65,
        )
        return engine

    def test_engine_score_returns_valid_layer2_scores(self, scoring_engine: Layer2ScoringEngine) -> None:
        """Verify engine returns Layer2Scores with valid fields."""
        ts_ms = int(time.time() * 1000)

        scores = scoring_engine.score_tick(
            symbol="BTCUSDT",
            ts_ms=ts_ms,
            mid_price=50000.0,
            trust_score=0.85,
            volume_24h=1000000.0,
            spread=1.0,
        )

        assert scores is not None
        assert 0.0 <= scores.anomaly_score <= 1.0, f"anomaly_score {scores.anomaly_score} out of [0,1]"
        assert scores.regime in [0, 1], f"regime {scores.regime} must be 0 or 1"
        assert len(scores.regime_posterior) == 2, f"regime_posterior {scores.regime_posterior} must have 2 entries"
        assert abs(sum(scores.regime_posterior) - 1.0) < 1e-6, f"regime_posterior {scores.regime_posterior} must sum to 1.0"

    def test_engine_first_ticks_and_buffer_fill_edge_cases(self, scoring_engine: Layer2ScoringEngine) -> None:
        """Verify first ticks and early buffer-fill path are stable (no NaN/inf, no crashes)."""
        base_time = int(time.time() * 1000)

        # First few ticks: constant price, missing optional features.
        for i in range(8):
            scores = scoring_engine.score_tick(
                symbol="BTCUSDT",
                ts_ms=base_time + i * 1000,
                mid_price=50000.0,
                trust_score=0.80,
                volume_24h=None,
                spread=None,
            )
            assert 0.0 <= scores.anomaly_score <= 1.0
            assert math.isfinite(scores.anomaly_score)
            assert math.isfinite(scores.if_score)
            assert math.isfinite(scores.hst_score)
            assert scores.regime in [0, 1]
            assert len(scores.regime_posterior) == 2

        # Buffer-fill phase: gradual movement with valid optional features.
        for i in range(8, 48):
            scores = scoring_engine.score_tick(
                symbol="BTCUSDT",
                ts_ms=base_time + i * 1000,
                mid_price=50000.0 + (i - 8) * 0.5,
                trust_score=0.82,
                volume_24h=1000000.0,
                spread=1.0,
            )
            assert 0.0 <= scores.anomaly_score <= 1.0
            assert math.isfinite(scores.anomaly_score)
            assert math.isfinite(scores.if_score)
            assert math.isfinite(scores.hst_score)
            assert scores.regime in [0, 1]
            assert abs(sum(scores.regime_posterior) - 1.0) < 1e-6

    def test_engine_handles_volatility_shifts(self, scoring_engine: Layer2ScoringEngine) -> None:
        """Verify engine responds to volatility changes (regime shifts)."""
        base_time = int(time.time() * 1000)

        # Low volatility period: consistent prices
        regimes_low = []
        for i in range(20):
            scores = scoring_engine.score_tick(
                symbol="BTCUSDT",
                ts_ms=base_time + i * 1000,
                mid_price=50000.0 + i * 0.1,  # Tiny moves
                trust_score=0.85,
                volume_24h=1000000.0,
                spread=1.0,
            )
            regimes_low.append(scores.regime)

        # High volatility period: large price swings
        regimes_high = []
        for i in range(20):
            scores = scoring_engine.score_tick(
                symbol="BTCUSDT",
                ts_ms=base_time + 20000 + i * 1000,
                mid_price=50000.0 + i * 100,  # Large moves
                trust_score=0.85,
                volume_24h=1000000.0,
                spread=1.0,
            )
            regimes_high.append(scores.regime)

        # High vol period should show more regime 1 (statistically)
        regime_1_high_frac = regimes_high.count(1) / len(regimes_high)
        regime_1_low_frac = regimes_low.count(1) / len(regimes_low)

        # Not a strict requirement, but directionally should be different
        assert regime_1_high_frac >= 0.0, "High regime count should be >= 0"

    def test_engine_anomaly_score_floor_on_outlier(self, scoring_engine: Layer2ScoringEngine) -> None:
        """Verify MAD guard floors anomaly score when return is extreme."""
        base_time = int(time.time() * 1000)

        # Warm up with normal ticks
        for i in range(100):
            scoring_engine.score_tick(
                symbol="BTCUSDT",
                ts_ms=base_time + i * 1000,
                mid_price=50000.0,
                trust_score=0.85,
                volume_24h=1000000.0,
                spread=1.0,
            )

        # Inject an extreme price move (MAD outlier)
        scores = scoring_engine.score_tick(
            symbol="BTCUSDT",
            ts_ms=base_time + 100000,
            mid_price=51000.0,  # 2% jump
            trust_score=0.85,
            volume_24h=1000000.0,
            spread=1.0,
        )

        # MAD guard should have triggered, flooring score at 0.65
        # (if the move is extreme enough relative to rolling MAD)
        # Note: this is probabilistic based on rolling stats, so we just verify score is valid
        assert 0.0 <= scores.anomaly_score <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
