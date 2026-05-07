"""Walk-forward validation tests for Phase 5 backtesting."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from services.backtesting.engine import BacktestConfig, BacktestResult
from services.backtesting.metrics import BacktestMetrics
from services.backtesting.walk_forward import build_walk_forward_windows, run_walk_forward


def test_build_walk_forward_windows_splits_range() -> None:
    start_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_time = datetime(2026, 1, 4, tzinfo=timezone.utc)

    windows = build_walk_forward_windows(start_time, end_time, fold_days=1)

    assert len(windows) == 3
    assert windows[0][0] == start_time
    assert windows[0][1] == datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert windows[-1][1] == end_time


def test_run_walk_forward_writes_summary(tmp_path: Path) -> None:
    base_config = BacktestConfig(
        symbol="BTCUSDT",
        scenario="baseline",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 3, tzinfo=timezone.utc),
        output_dir=tmp_path / "reports",
    )

    def fake_runner(config: BacktestConfig) -> BacktestResult:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = config.output_dir / "report.html"
        equity_curve_path = config.output_dir / "equity_curve.csv"
        report_path.write_text("<html>ok</html>", encoding="utf-8")
        equity_curve_path.write_text("timestamp_utc\n", encoding="utf-8")
        metrics = BacktestMetrics(
            run_id=f"{config.start_time:%Y%m%d}",
            start_time=config.start_time,
            end_time=config.end_time,
            symbol=config.symbol,
            scenario=config.scenario,
            sharpe_ratio=1.23,
            equity_curve_path=str(equity_curve_path),
            total_ticks=1,
        )
        return BacktestResult(config=config, metrics=metrics, report_path=report_path, equity_curve_path=equity_curve_path)

    result = run_walk_forward(base_config, fold_days=1, minimum_folds=2, engine_runner=fake_runner)

    assert len(result.folds) == 2
    assert result.summary_path.exists()
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["average_sharpe"] == 1.23
    assert summary["folds"][0]["metrics"]["symbol"] == "BTCUSDT"