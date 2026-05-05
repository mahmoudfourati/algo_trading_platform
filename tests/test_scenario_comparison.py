"""Tests for scenario comparison module."""

from __future__ import annotations

from datetime import datetime, timezone

from services.backtesting.metrics import BacktestMetrics
from services.backtesting.scenario_comparison import (
    MetricDelta,
    ScenarioComparison,
    compare_scenarios,
    build_comparison_dashboard,
)


def test_metric_delta_serializes() -> None:
    """Verify MetricDelta serializes to dict."""
    delta = MetricDelta(
        metric_name="sharpe_ratio",
        baseline_value=1.5,
        attack_value=1.0,
        delta=-0.5,
        percent_change=-33.33,
        direction="worse",
    )

    payload = delta.to_dict()
    assert payload["metric_name"] == "sharpe_ratio"
    assert payload["delta"] == -0.5
    assert payload["direction"] == "worse"


def test_compare_scenarios_computes_deltas() -> None:
    """Verify scenario comparison computes correct deltas."""
    baseline = BacktestMetrics(
        run_id="baseline_001",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        symbol="BTCUSDT",
        scenario="baseline",
        gross_pnl=100.0,
        net_pnl=90.0,
        sharpe_ratio=2.0,
        max_drawdown=0.05,
        win_rate=0.6,
        end_to_end_latency_ms=10.0,
        normal_state_pct=0.8,
        permutation_p_value=0.01,
        equity_curve_path="curve.csv",
        injected_anomalies=0,
        detected_anomalies=0,
        false_positives=0,
        total_ticks=1000,
        events=[],
    )

    attack = BacktestMetrics(
        run_id="attack_001",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        symbol="BTCUSDT",
        scenario="flash_crash",
        gross_pnl=80.0,
        net_pnl=70.0,
        sharpe_ratio=1.5,
        max_drawdown=0.10,
        win_rate=0.5,
        end_to_end_latency_ms=12.0,
        normal_state_pct=0.6,
        permutation_p_value=0.15,
        equity_curve_path="curve.csv",
        injected_anomalies=50,
        detected_anomalies=45,
        false_positives=2,
        total_ticks=1000,
        events=[],
    )

    comparison = compare_scenarios(baseline, attack, "flash_crash")

    assert comparison.scenario_name == "flash_crash"
    assert len(comparison.deltas) == 10
    # Verify a few specific deltas
    sharpe_delta = next(d for d in comparison.deltas if d.metric_name == "sharpe_ratio")
    assert sharpe_delta.baseline_value == 2.0
    assert sharpe_delta.attack_value == 1.5
    assert sharpe_delta.delta == -0.5
    assert sharpe_delta.percent_change == -25.0
    assert sharpe_delta.direction == "worse"

    # Drawdown (lower is better)
    drawdown_delta = next(d for d in comparison.deltas if d.metric_name == "max_drawdown")
    assert drawdown_delta.baseline_value == 0.05
    assert drawdown_delta.attack_value == 0.10
    assert drawdown_delta.delta == 0.05
    assert drawdown_delta.direction == "worse"  # Attack increased drawdown


def test_direction_logic() -> None:
    """Verify direction logic for various metrics."""
    # Sharpe: higher is better
    baseline = BacktestMetrics(
        run_id="b1",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        symbol="BTCUSDT",
        scenario="baseline",
        gross_pnl=100.0,
        net_pnl=90.0,
        sharpe_ratio=2.0,
        max_drawdown=0.05,
        win_rate=0.6,
        end_to_end_latency_ms=10.0,
        normal_state_pct=0.8,
        permutation_p_value=0.01,
        equity_curve_path="c.csv",
        injected_anomalies=0,
        detected_anomalies=0,
        false_positives=0,
        total_ticks=1000,
        events=[],
    )

    attack_improved_sharpe = BacktestMetrics(
        run_id="a1",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        symbol="BTCUSDT",
        scenario="flash_crash",
        gross_pnl=120.0,
        net_pnl=110.0,
        sharpe_ratio=2.5,
        max_drawdown=0.04,
        win_rate=0.7,
        end_to_end_latency_ms=9.0,
        normal_state_pct=0.85,
        permutation_p_value=0.005,
        equity_curve_path="c.csv",
        injected_anomalies=50,
        detected_anomalies=45,
        false_positives=1,
        total_ticks=1000,
        events=[],
    )

    comparison = compare_scenarios(baseline, attack_improved_sharpe, "test")
    sharpe_delta = next(d for d in comparison.deltas if d.metric_name == "sharpe_ratio")
    assert sharpe_delta.direction == "better"  # Attack improved Sharpe


def test_build_comparison_dashboard() -> None:
    """Verify dashboard builder aggregates multiple scenarios."""
    baseline = BacktestMetrics(
        run_id="base",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        symbol="BTCUSDT",
        scenario="baseline",
        gross_pnl=100.0,
        net_pnl=90.0,
        sharpe_ratio=2.0,
        max_drawdown=0.05,
        win_rate=0.6,
        end_to_end_latency_ms=10.0,
        normal_state_pct=0.8,
        permutation_p_value=0.01,
        equity_curve_path="c.csv",
        injected_anomalies=0,
        detected_anomalies=0,
        false_positives=0,
        total_ticks=1000,
        events=[],
    )

    flash_crash_metrics = BacktestMetrics(
        run_id="fc",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        symbol="BTCUSDT",
        scenario="flash_crash",
        gross_pnl=80.0,
        net_pnl=70.0,
        sharpe_ratio=1.5,
        max_drawdown=0.10,
        win_rate=0.5,
        end_to_end_latency_ms=12.0,
        normal_state_pct=0.6,
        permutation_p_value=0.15,
        equity_curve_path="c.csv",
        injected_anomalies=50,
        detected_anomalies=45,
        false_positives=2,
        total_ticks=1000,
        events=[],
    )

    spread_spike_metrics = BacktestMetrics(
        run_id="ss",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        symbol="BTCUSDT",
        scenario="spread_spike",
        gross_pnl=95.0,
        net_pnl=85.0,
        sharpe_ratio=1.8,
        max_drawdown=0.06,
        win_rate=0.55,
        end_to_end_latency_ms=11.0,
        normal_state_pct=0.75,
        permutation_p_value=0.05,
        equity_curve_path="c.csv",
        injected_anomalies=30,
        detected_anomalies=28,
        false_positives=1,
        total_ticks=1000,
        events=[],
    )

    attack_metrics = {
        "flash_crash": flash_crash_metrics,
        "spread_spike": spread_spike_metrics,
    }

    dashboard = build_comparison_dashboard(baseline, attack_metrics)

    assert len(dashboard) == 2
    assert dashboard[0].scenario_name in ["flash_crash", "spread_spike"]
    assert dashboard[1].scenario_name in ["flash_crash", "spread_spike"]

    # Verify deltas are present for both
    for comparison in dashboard:
        assert len(comparison.deltas) == 10
        assert comparison.baseline_metrics.run_id == "base"
