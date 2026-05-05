"""Scenario comparison utilities for Phase 5 backtesting reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .metrics import BacktestMetrics


@dataclass(frozen=True)
class MetricDelta:
    """Delta between baseline and attack scenario for a single metric."""

    metric_name: str
    baseline_value: float
    attack_value: float
    delta: float
    percent_change: float
    direction: str  # "better", "worse", "neutral"

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_name": self.metric_name,
            "baseline_value": self.baseline_value,
            "attack_value": self.attack_value,
            "delta": self.delta,
            "percent_change": self.percent_change,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class ScenarioComparison:
    """Comparison between baseline and an attack scenario."""

    scenario_name: str
    baseline_metrics: BacktestMetrics
    attack_metrics: BacktestMetrics
    deltas: list[MetricDelta]

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_name": self.scenario_name,
            "baseline_run_id": self.baseline_metrics.run_id,
            "attack_run_id": self.attack_metrics.run_id,
            "deltas": [d.to_dict() for d in self.deltas],
        }


def _compute_direction(metric_name: str, percent_change: float) -> str:
    """Determine if a change is 'better', 'worse', or 'neutral' depending on the metric."""
    if abs(percent_change) < 0.01:
        return "neutral"

    # Metrics where higher is better
    better_when_positive = {"sharpe_ratio", "win_rate", "normal_state_pct", "net_pnl", "gross_pnl"}
    # Metrics where lower is better
    better_when_negative = {"max_drawdown", "false_positives", "end_to_end_latency_ms", "permutation_p_value"}

    if metric_name in better_when_positive:
        return "better" if percent_change > 0 else "worse"
    elif metric_name in better_when_negative:
        return "better" if percent_change < 0 else "worse"
    else:
        # For detection_rate, higher is better
        if metric_name == "detection_rate":
            return "better" if percent_change > 0 else "worse"
        return "neutral"


def compare_scenarios(
    baseline_metrics: BacktestMetrics,
    attack_metrics: BacktestMetrics,
    scenario_name: str,
) -> ScenarioComparison:
    """Compare baseline metrics against an attack scenario.

    Args:
        baseline_metrics: Metrics from baseline (no-attack) run
        attack_metrics: Metrics from attack scenario run
        scenario_name: Name of the attack scenario (e.g., "flash_crash")

    Returns:
        ScenarioComparison with computed deltas
    """

    deltas: list[MetricDelta] = []

    # Core metrics to compare
    metric_pairs = [
        ("sharpe_ratio", baseline_metrics.sharpe_ratio, attack_metrics.sharpe_ratio),
        ("max_drawdown", baseline_metrics.max_drawdown, attack_metrics.max_drawdown),
        ("win_rate", baseline_metrics.win_rate, attack_metrics.win_rate),
        ("net_pnl", baseline_metrics.net_pnl, attack_metrics.net_pnl),
        ("gross_pnl", baseline_metrics.gross_pnl, attack_metrics.gross_pnl),
        ("detection_rate", baseline_metrics.get_detection_rate(), attack_metrics.get_detection_rate()),
        ("false_positive_rate", baseline_metrics.get_false_positive_rate(), attack_metrics.get_false_positive_rate()),
        ("normal_state_pct", baseline_metrics.normal_state_pct, attack_metrics.normal_state_pct),
        ("end_to_end_latency_ms", baseline_metrics.end_to_end_latency_ms, attack_metrics.end_to_end_latency_ms),
        ("permutation_p_value", baseline_metrics.permutation_p_value, attack_metrics.permutation_p_value),
    ]

    for metric_name, baseline_val, attack_val in metric_pairs:
        delta = attack_val - baseline_val
        # Avoid division by zero for percent change
        if abs(baseline_val) < 1e-12:
            percent_change = 0.0 if abs(delta) < 1e-12 else (100.0 if delta > 0 else -100.0)
        else:
            percent_change = (delta / baseline_val) * 100.0

        direction = _compute_direction(metric_name, percent_change)

        deltas.append(
            MetricDelta(
                metric_name=metric_name,
                baseline_value=baseline_val,
                attack_value=attack_val,
                delta=delta,
                percent_change=percent_change,
                direction=direction,
            )
        )

    return ScenarioComparison(
        scenario_name=scenario_name,
        baseline_metrics=baseline_metrics,
        attack_metrics=attack_metrics,
        deltas=deltas,
    )


def build_comparison_dashboard(
    baseline_metrics: BacktestMetrics,
    attack_metrics_dict: dict[str, BacktestMetrics],
) -> list[ScenarioComparison]:
    """Build a full comparison dashboard across multiple attack scenarios.

    Args:
        baseline_metrics: Metrics from baseline (no-attack) run
        attack_metrics_dict: Dict mapping scenario name -> attack metrics

    Returns:
        List of ScenarioComparison objects (one per scenario)
    """

    comparisons = []
    for scenario_name, attack_metrics in attack_metrics_dict.items():
        comparison = compare_scenarios(baseline_metrics, attack_metrics, scenario_name)
        comparisons.append(comparison)

    return comparisons
