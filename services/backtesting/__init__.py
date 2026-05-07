"""Backtesting package for Phase 5 historical replay and validation."""

from .engine import BacktestConfig, BacktestEngine, BacktestResult
from .permutation_test import PermutationTestResult, run_permutation_test
from .results_db import ResultsDB
from .walk_forward import (
    WalkForwardFold,
    WalkForwardResult,
    build_walk_forward_windows,
    run_walk_forward,
)

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "PermutationTestResult",
    "ResultsDB",
    "WalkForwardFold",
    "WalkForwardResult",
    "build_walk_forward_windows",
    "run_permutation_test",
    "run_walk_forward",
]
from .scenario_comparison import ScenarioComparison, compare_scenarios, build_comparison_dashboard

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "PermutationTestResult",
    "ResultsDB",
    "ScenarioComparison",
    "WalkForwardFold",
    "WalkForwardResult",
    "build_comparison_dashboard",
    "build_walk_forward_windows",
    "compare_scenarios",
    "run_permutation_test",
    "run_walk_forward",
]
