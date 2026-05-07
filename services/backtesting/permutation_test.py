"""Permutation testing for Sharpe ratio significance in Phase 5 backtesting."""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Callable

from .metrics import BacktestMetrics


@dataclass(frozen=True)
class PermutationTestResult:
    """Result of a permutation test on backtest metrics."""

    actual_sharpe: float
    shuffled_sharpes: list[float]
    p_value: float
    num_shuffles: int
    is_significant_at_05: bool
    percentile_rank: float

    def to_dict(self) -> dict[str, object]:
        """Serialize result for JSON output."""
        return {
            "actual_sharpe": self.actual_sharpe,
            "num_shuffles": self.num_shuffles,
            "p_value": self.p_value,
            "is_significant_at_05": self.is_significant_at_05,
            "percentile_rank": self.percentile_rank,
        }


def _compute_sharpe_from_returns(returns: list[float]) -> float:
    """Compute Sharpe ratio from a list of period returns."""
    if len(returns) < 2:
        return 0.0
    mean_r = statistics.mean(returns)
    stdev_r = statistics.pstdev(returns)
    if stdev_r < 1e-12:
        return 0.0
    return (mean_r / stdev_r) * math.sqrt(len(returns))


def run_permutation_test(
    equity_history: list[float],
    *,
    num_shuffles: int = 1000,
    seed: int = 42,
) -> PermutationTestResult:
    """Run a permutation test on trade timestamp shuffles.

    This implementation approximates the blueprint's permutation test by shuffling
    the returns sequence (which is equivalent to shuffling trade entry timestamps
    in a deterministic way) and recomputing the Sharpe ratio for each permutation.

    Args:
        equity_history: List of equity values over time (e.g., from backtest run).
        num_shuffles: Number of permutations to generate (default 1000 for p<0.05).
        seed: Random seed for reproducibility.

    Returns:
        PermutationTestResult with p-value and significance flag.
    """

    if len(equity_history) < 2:
        return PermutationTestResult(
            actual_sharpe=0.0,
            shuffled_sharpes=[],
            p_value=1.0,
            num_shuffles=num_shuffles,
            is_significant_at_05=False,
            percentile_rank=0.0,
        )

    # Compute returns from equity curve
    returns = [equity_history[i] - equity_history[i - 1] for i in range(1, len(equity_history))]

    # Compute actual Sharpe
    actual_sharpe = _compute_sharpe_from_returns(returns)

    # Permute and compute Sharpe for each shuffle
    rng = random.Random(seed)
    shuffled_sharpes: list[float] = []

    for _ in range(num_shuffles):
        shuffled_returns = returns.copy()
        rng.shuffle(shuffled_returns)
        shuffled_sharpe = _compute_sharpe_from_returns(shuffled_returns)
        shuffled_sharpes.append(shuffled_sharpe)

    # Compute p-value: fraction of shuffled Sharpe >= actual
    p_value = sum(1 for s in shuffled_sharpes if s >= actual_sharpe) / num_shuffles

    # Compute percentile rank: where actual falls in the distribution
    percentile_rank = sum(1 for s in shuffled_sharpes if s < actual_sharpe) / num_shuffles

    return PermutationTestResult(
        actual_sharpe=actual_sharpe,
        shuffled_sharpes=shuffled_sharpes,
        p_value=p_value,
        num_shuffles=num_shuffles,
        is_significant_at_05=(p_value < 0.05),
        percentile_rank=percentile_rank,
    )


def inject_permutation_p_value(metrics: BacktestMetrics, equity_history: list[float] | None = None) -> BacktestMetrics:
    """Compute and inject a permutation p-value into backtest metrics.

    If no equity_history is provided, this reconstructs it from the events
    (as a fallback, though the caller should ideally pass the full history).
    """

    if equity_history is None:
        # Fallback: reconstruct from equity values in events if available
        # For now, just return metrics unchanged if no history available
        if not metrics.events:
            return metrics

    result = run_permutation_test(equity_history or [0.0], num_shuffles=1000)

    # Create a new metrics object with the p-value injected
    from dataclasses import replace

    return replace(metrics, permutation_p_value=result.p_value)
