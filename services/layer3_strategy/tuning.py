"""Tuning utilities for Phase 6.8: parameter sweeps and result snapshots.

Provides a lightweight grid-search runner that uses the Phase-5
BacktestEngine to evaluate combinations of BacktestConfig-level
parameters. Currently supports engine-level parameter sweeps (trust/
anomaly/weights). Layer-3 specific threshold tuning hooks are planned
and stubbed here for later integration.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from itertools import product
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from services.backtesting.engine import BacktestConfig, BacktestEngine


@dataclass(frozen=True)
class TuningResult:
    params: Dict[str, Any]
    metrics: Dict[str, Any]
    report_path: Optional[str]


class BacktestTuner:
    """Simple grid-search tuner that runs BacktestEngine over parameter grids.

    Notes:
    - The runner currently accepts BacktestConfig field names as grid keys
      (for example: `trust_threshold`, `anomaly_threshold`, `if_weight`).
    - Layer-3 threshold tuning requires hook points in the backtest engine
      to collect indicator snapshots; that integration is planned separately.
    """

    def __init__(self, *, output_dir: Path = Path("artifacts/tuning")) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _iter_param_combinations(self, grid: Mapping[str, Iterable[Any]]) -> Iterable[Dict[str, Any]]:
        keys = list(grid.keys())
        pools = [list(grid[k]) for k in keys]
        for values in product(*pools):
            yield dict(zip(keys, values))

    def run_grid_search(self, *, base_config: BacktestConfig, grid: Mapping[str, Iterable[Any]]) -> List[TuningResult]:
        results: List[TuningResult] = []
        for params in self._iter_param_combinations(grid):
            # create a shallow copy of base_config and override attributes present in params
            cfg_kwargs = {**asdict(base_config)} if hasattr(base_config, "__dict__") else base_config.__dict__.copy()
            cfg_kwargs.update(params)
            # construct BacktestConfig dataclass from kwargs
            cfg = BacktestConfig(**{k: v for k, v in cfg_kwargs.items() if k in BacktestConfig.__annotations__})
            try:
                engine = BacktestEngine(cfg)
                result = engine.run()
                metrics = result.metrics.to_dict()
                report_path = str(result.report_path)
            except Exception as exc:  # pragmatic: capture failures and continue
                metrics = {"error": repr(exc)}
                report_path = None

            tuning_result = TuningResult(params=params, metrics=metrics, report_path=report_path)
            results.append(tuning_result)

        # persist results snapshot
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_file = self.output_dir / f"tuning_results_{ts}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump([{"params": r.params, "metrics": r.metrics, "report_path": r.report_path} for r in results], f, indent=2, sort_keys=True)

        return results


def quick_default_grid() -> Dict[str, Iterable[Any]]:
    return {
        "trust_threshold": [0.55, 0.6, 0.65],
        "anomaly_threshold": [0.60, 0.65, 0.70],
        "if_weight": [0.4, 0.45, 0.5],
        "hst_weight": [0.5, 0.55, 0.6],
    }
