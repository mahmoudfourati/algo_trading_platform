from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class VolPoint:
    end_time_ms: int
    realized_vol: float


def compute_log_returns(prices: Sequence[float]) -> List[float]:
    rets: List[float] = []
    for i in range(1, len(prices)):
        p0 = prices[i - 1]
        p1 = prices[i]
        if p0 <= 0 or p1 <= 0:
            continue
        rets.append(math.log(p1 / p0))
    return rets


def realized_vol_30m(*, times_ms: Sequence[int], closes: Sequence[float]) -> List[VolPoint]:
    """Compute 30-minute realized volatility from 1-minute close prices.

    For each non-overlapping 30-minute bucket, compute:
      RV = sqrt(sum_{t in bucket} r_t^2)
    where r_t are 1-minute log returns.
    """

    if len(times_ms) != len(closes):
        raise ValueError("times_ms and closes length mismatch")
    if len(closes) < 31:
        return []

    bucket_ms = 30 * 60 * 1000

    out: List[VolPoint] = []
    bucket_start = times_ms[0] - (times_ms[0] % bucket_ms)

    cur_times: List[int] = []
    cur_prices: List[float] = []

    for t, p in zip(times_ms, closes):
        # Advance buckets until t fits.
        while t >= bucket_start + bucket_ms:
            if len(cur_prices) >= 2:
                r = compute_log_returns(cur_prices)
                rv = math.sqrt(sum(x * x for x in r))
                out.append(VolPoint(end_time_ms=bucket_start + bucket_ms, realized_vol=rv))
            bucket_start += bucket_ms
            cur_times = []
            cur_prices = []

        cur_times.append(t)
        cur_prices.append(p)

    # Flush final bucket.
    if len(cur_prices) >= 2:
        r = compute_log_returns(cur_prices)
        rv = math.sqrt(sum(x * x for x in r))
        out.append(VolPoint(end_time_ms=bucket_start + bucket_ms, realized_vol=rv))

    return out
