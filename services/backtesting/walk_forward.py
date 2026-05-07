"""Walk-forward validation helpers for Phase 5 backtesting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .engine import BacktestConfig, BacktestEngine, BacktestResult
from .metrics import BacktestMetrics


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_walk_forward_windows(
    start_time: datetime,
    end_time: datetime,
    *,
    fold_days: int = 15,
) -> list[tuple[datetime, datetime]]:
    """Split a replay range into contiguous walk-forward windows."""

    if fold_days <= 0:
        raise ValueError("fold_days must be positive")

    windows: list[tuple[datetime, datetime]] = []
    cursor = _utc(start_time)
    finish = _utc(end_time)
    fold_delta = timedelta(days=fold_days)

    while cursor < finish:
        window_end = min(cursor + fold_delta, finish)
        windows.append((cursor, window_end))
        cursor = window_end

    return windows


@dataclass(frozen=True)
class WalkForwardFold:
    """Result of one walk-forward fold."""

    fold_index: int
    start_time: datetime
    end_time: datetime
    metrics: BacktestMetrics
    report_path: Path
    equity_curve_path: Path

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["start_time"] = _utc(self.start_time).isoformat()
        payload["end_time"] = _utc(self.end_time).isoformat()
        payload["report_path"] = str(self.report_path)
        payload["equity_curve_path"] = str(self.equity_curve_path)
        payload["metrics"] = self.metrics.to_dict()
        return payload


@dataclass
class WalkForwardResult:
    """Aggregate output of a walk-forward validation run."""

    base_config: BacktestConfig
    folds: list[WalkForwardFold]
    summary_path: Path

    def average_sharpe(self) -> float:
        if not self.folds:
            return 0.0
        return sum(fold.metrics.sharpe_ratio for fold in self.folds) / len(self.folds)

    def to_dict(self) -> dict[str, object]:
        return {
            "base_config": _config_snapshot(self.base_config),
            "folds": [fold.to_dict() for fold in self.folds],
            "average_sharpe": self.average_sharpe(),
            "summary_path": str(self.summary_path),
        }


def _config_snapshot(config: BacktestConfig) -> dict[str, object]:
    snapshot = asdict(config)
    for key, value in list(snapshot.items()):
        if isinstance(value, Path):
            snapshot[key] = str(value)
        elif isinstance(value, tuple):
            snapshot[key] = list(value)
        elif isinstance(value, datetime):
            snapshot[key] = _utc(value).isoformat()
    return snapshot


def run_walk_forward(
    base_config: BacktestConfig,
    *,
    fold_days: int = 15,
    minimum_folds: int = 3,
    engine_runner: Callable[[BacktestConfig], BacktestResult] | None = None,
) -> WalkForwardResult:
    """Run walk-forward validation over contiguous windows.

    The default runner uses the existing BacktestEngine so this module stays
    aligned with the live replay path.
    """

    windows = build_walk_forward_windows(base_config.start_time, base_config.end_time, fold_days=fold_days)
    if len(windows) < minimum_folds:
        raise ValueError(f"walk-forward requires at least {minimum_folds} folds, got {len(windows)}")

    summary_dir = base_config.output_dir / "walk_forward"
    summary_dir.mkdir(parents=True, exist_ok=True)
    runner = engine_runner or (lambda config: BacktestEngine(config).run())

    folds: list[WalkForwardFold] = []
    for fold_index, (window_start, window_end) in enumerate(windows, start=1):
        fold_config = replace(
            base_config,
            start_time=window_start,
            end_time=window_end,
            output_dir=summary_dir / f"fold_{fold_index:02d}",
        )
        fold_result = runner(fold_config)
        folds.append(
            WalkForwardFold(
                fold_index=fold_index,
                start_time=window_start,
                end_time=window_end,
                metrics=fold_result.metrics,
                report_path=fold_result.report_path,
                equity_curve_path=fold_result.equity_curve_path,
            )
        )

    result = WalkForwardResult(base_config=base_config, folds=folds, summary_path=summary_dir / "walk_forward_summary.json")
    result.summary_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return result