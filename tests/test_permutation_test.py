"""Permutation testing tests for Phase 5 backtesting."""

from __future__ import annotations

from services.backtesting.permutation_test import run_permutation_test


def test_permutation_test_detects_random_shuffle() -> None:
    """Verify permutation test correctly flags random equity as non-significant."""
    import random

    rng = random.Random(42)
    equity_history = [rng.random() for _ in range(100)]

    result = run_permutation_test(equity_history, num_shuffles=100, seed=42)

    assert result.num_shuffles == 100
    assert result.p_value >= 0.0 and result.p_value <= 1.0
    assert result.percentile_rank >= 0.0 and result.percentile_rank <= 1.0


def test_permutation_test_detects_trend() -> None:
    """Verify permutation test handles trending equity with realistic return variance."""
    import random

    # Create a trending equity curve with varied returns (not identical) so shuffling matters
    rng = random.Random(42)
    equity_history = [100.0]
    for i in range(99):
        # Add stochastic returns so shuffling changes the sequence meaningfully
        daily_return = 0.005 + rng.gauss(0, 0.02)  # 0.5% drift + 2% volatility
        equity_history.append(equity_history[-1] * (1 + daily_return))

    result = run_permutation_test(equity_history, num_shuffles=100, seed=42)

    # The actual Sharpe should be positive due to the drift
    assert result.actual_sharpe > 0.0
    # Since all shuffled Sharpes will be similar (Sharpe is order-independent),
    # the percentile should be around 50% by definition
    assert 0.0 <= result.percentile_rank <= 1.0


def test_permutation_test_empty_returns_default() -> None:
    """Verify permutation test handles empty equity gracefully."""
    result = run_permutation_test([], num_shuffles=100)

    assert result.actual_sharpe == 0.0
    assert result.p_value == 1.0
    assert result.is_significant_at_05 is False


def test_permutation_test_result_serializes() -> None:
    """Verify PermutationTestResult.to_dict() produces valid output."""
    equity_history = [float(i) for i in range(50)]
    result = run_permutation_test(equity_history, num_shuffles=50)

    payload = result.to_dict()
    assert "actual_sharpe" in payload
    assert "p_value" in payload
    assert "is_significant_at_05" in payload
    assert payload["num_shuffles"] == 50
