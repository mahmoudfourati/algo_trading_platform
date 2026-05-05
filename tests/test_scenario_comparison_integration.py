"""Integration tests for scenario comparison reporting in HTML reports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from services.backtesting.metrics import BacktestMetrics
from services.backtesting.report_generator import BacktestReportGenerator
from services.backtesting.scenario_comparison import compare_scenarios


def test_report_generator_renders_comparison(tmp_path: Path) -> None:
    """Verify that BacktestReportGenerator can render comparison dashboard."""
    from services.backtesting.engine import BacktestConfig

    output_dir = tmp_path / "reports"
    output_dir.mkdir()

    # Create baseline config and metrics
    baseline_config = BacktestConfig(
        symbol="BTCUSDT",
        scenario="baseline",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        output_dir=output_dir,
    )

    baseline_metrics = BacktestMetrics(
        run_id="base_001",
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

    # Create attack scenario metrics
    attack_metrics = BacktestMetrics(
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

    # Create comparison
    comparison = compare_scenarios(baseline_metrics, attack_metrics, "flash_crash")

    # Render report with comparison
    generator = BacktestReportGenerator(output_dir)
    report_html = generator.render(
        config=baseline_config, metrics=baseline_metrics, comparisons=[comparison]
    )

    # Verify HTML contains comparison sections
    assert "Scenario Comparison Dashboard" in report_html
    assert "flash_crash" in report_html.lower() or "Flash_Crash" in report_html
    assert "Metric" in report_html
    assert "Baseline" in report_html
    assert "Attack" in report_html
    assert "Delta" in report_html
    assert "Change %" in report_html
    assert "sharpe_ratio" in report_html
    assert "max_drawdown" in report_html


def test_report_generator_without_comparison(tmp_path: Path) -> None:
    """Verify that report generator works fine with no comparisons."""
    from services.backtesting.engine import BacktestConfig

    output_dir = tmp_path / "reports"
    output_dir.mkdir()

    config = BacktestConfig(
        symbol="BTCUSDT",
        scenario="baseline",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        output_dir=output_dir,
    )

    metrics = BacktestMetrics(
        run_id="base_001",
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

    generator = BacktestReportGenerator(output_dir)
    report_html = generator.render(config=config, metrics=metrics)

    # Verify report still renders without comparison section
    assert "Phase 5 Backtest Report" in report_html
    assert "Config Snapshot" in report_html
    assert "Scenario Comparison Dashboard" not in report_html
