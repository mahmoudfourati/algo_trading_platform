"""Offline HMM training entrypoint.

Downloads historical data, builds features, trains a GaussianHMM, and writes artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

from services.hmm_training.binance_vision import date_range, download_daily_klines, iter_daily_close_prices
from services.hmm_training.features import realized_vol_30m


@dataclass(frozen=True)
class TrainingMetadata:
    symbols: List[str]
    interval: str
    days: int
    end_date: str
    points: int
    n_states: int
    regime_order_by_mean: List[int]
    regime_means: List[float]


def _load_series(*, symbol: str, interval: str, days: int, end_date: date, cache_dir: Path) -> Tuple[List[int], List[float]]:
    times: List[int] = []
    closes: List[float] = []

    for d in date_range(end_inclusive=end_date, days=days):
        try:
            zp = download_daily_klines(symbol=symbol, interval=interval, day=d, cache_dir=cache_dir)
        except FileNotFoundError:
            # Binance Vision daily files may lag (e.g. today's file not posted yet).
            continue
        for row in iter_daily_close_prices(zp):
            times.append(row.open_time_ms)
            closes.append(row.close_price)

    # Ensure sorted by time.
    pairs = sorted(zip(times, closes), key=lambda x: x[0])
    times = [t for t, _ in pairs]
    closes = [p for _, p in pairs]
    return times, closes


def train_gaussian_hmm(vol_series: List[float], *, n_states: int = 2, seed: int = 42):
    try:
        import numpy as np
        from hmmlearn.hmm import GaussianHMM
    except Exception as e:
        raise RuntimeError(
            "Missing ML dependencies. Install numpy + hmmlearn (see requirements-ml.txt)."
        ) from e

    X = np.array(vol_series, dtype=float).reshape(-1, 1)

    model = GaussianHMM(
        n_components=n_states,
        covariance_type="diag",
        n_iter=200,
        random_state=seed,
    )
    model.fit(X)

    means = model.means_.reshape(-1)
    order = [int(x) for x in np.argsort(means)]
    return model, order, [float(x) for x in means.tolist()]


def save_artifacts(
    *,
    out_dir: Path,
    model,
    metadata: TrainingMetadata,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save model via joblib (blueprint requirement; hmmlearn models are picklable).
    import joblib

    joblib.dump(model, out_dir / "model.pkl")
    (out_dir / "metadata.json").write_text(json.dumps(asdict(metadata), indent=2, sort_keys=True), encoding="utf-8")


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 3: Train 2-state GaussianHMM on 30m realized volatility")
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT", help="Comma-separated Binance symbols")
    p.add_argument("--interval", default="1m", help="Kline interval (Binance Vision)")
    p.add_argument("--days", type=int, default=90, help="Number of days to download")
    p.add_argument(
        "--end-date",
        default=(date.today() - timedelta(days=1)).isoformat(),
        help="End date (YYYY-MM-DD). Default is yesterday to avoid Binance Vision daily-file lag.",
    )
    p.add_argument("--cache-dir", default=os.path.join("data", "binance_vision"), help="Download cache")
    p.add_argument("--out-dir", default=os.path.join("artifacts", "hmm"), help="Output directory")
    args = p.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    end_date = date.fromisoformat(args.end_date)

    cache_dir = Path(args.cache_dir)

    # Build a single combined volatility series by concatenating symbols.
    vol_all: List[float] = []
    for sym in symbols:
        times, closes = _load_series(symbol=sym, interval=args.interval, days=args.days, end_date=end_date, cache_dir=cache_dir)
        pts = realized_vol_30m(times_ms=times, closes=closes)
        vol = [p.realized_vol for p in pts]
        vol_all.extend(vol)

    if len(vol_all) < 50:
        raise SystemExit(f"Not enough data points to train HMM (got {len(vol_all)})")

    model, order, means = train_gaussian_hmm(vol_all, n_states=2, seed=42)

    meta = TrainingMetadata(
        symbols=symbols,
        interval=args.interval,
        days=args.days,
        end_date=args.end_date,
        points=len(vol_all),
        n_states=2,
        regime_order_by_mean=order,
        regime_means=means,
    )

    save_artifacts(out_dir=Path(args.out_dir), model=model, metadata=meta)

    print(f"Saved model to {Path(args.out_dir) / 'model.pkl'}")
    print(f"Saved metadata to {Path(args.out_dir) / 'metadata.json'}")
    print(f"Regime means: {means} (order low->high: {order})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
