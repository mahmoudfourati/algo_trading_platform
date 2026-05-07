"""Layer 1 ingestion soak runner.

Runs adapters for an extended duration and writes periodic health/status to logs.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from .adapters.binance import BinanceAdapter
from .adapters.bybit import BybitAdapter
from .adapters.coinbase import CoinbaseAdapter
from .adapters.kraken import KrakenAdapter
from .adapters.okx import OkxAdapter


def _parse_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _symbols() -> list[str]:
    return _parse_csv(os.getenv("SYMBOLS", "BTC-USDT,ETH-USDT"))


def _duration_s() -> int:
    return int(os.getenv("DURATION_S", "1800"))


def _status_interval_s() -> int:
    return int(os.getenv("STATUS_INTERVAL_S", "60"))


def _stale_threshold_s() -> float:
    # Some feeds can be quiet; heartbeat is ping/pong, not tick frequency.
    return float(os.getenv("STALE_THRESHOLD_S", "120"))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _default_log_path() -> Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    return Path("logs") / f"layer1_soak_{ts}.log"


def _log_path() -> Path:
    raw = os.getenv("LOG_PATH")
    if raw:
        return Path(raw)
    return _default_log_path()


async def main() -> None:
    symbols = _symbols()
    duration_s = _duration_s()
    status_interval_s = _status_interval_s()
    stale_threshold_s = _stale_threshold_s()
    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Tee adapter audit events into the same log file.
    os.environ["AUDIT_LOG_PATH"] = str(log_path)

    def log(line: str) -> None:
        print(line)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    log(f"SOAK_START log_path={log_path.as_posix()} duration_s={duration_s} symbols={symbols}")

    adapters = [
        BinanceAdapter(symbols),
        CoinbaseAdapter(symbols),
        KrakenAdapter(symbols),
        OkxAdapter(symbols),
        BybitAdapter(symbols),
    ]

    tick_counts: dict[str, int] = {a.exchange_id: 0 for a in adapters}
    last_tick_ms: dict[str, int] = {a.exchange_id: 0 for a in adapters}

    stop = asyncio.Event()

    async def consume(adapter) -> None:
        async for tick in adapter.run_forever():
            tick_counts[adapter.exchange_id] += 1
            last_tick_ms[adapter.exchange_id] = tick.received_timestamp_ms
            if stop.is_set():
                break

    async def status_loop() -> None:
        while not stop.is_set():
            await asyncio.sleep(status_interval_s)
            now = _now_ms()
            statuses = []
            for ex in tick_counts:
                age_s = (now - last_tick_ms[ex]) / 1000.0 if last_tick_ms[ex] else None
                statuses.append(
                    f"{ex}:count={tick_counts[ex]},last_age_s={age_s:.1f}" if age_s is not None else f"{ex}:count={tick_counts[ex]},last_age_s=None"
                )
            log("SOAK_STATUS " + " | ".join(statuses))

    consumer_tasks = [asyncio.create_task(consume(a), name=f"consume:{a.exchange_id}") for a in adapters]
    status_task = asyncio.create_task(status_loop(), name="status")

    try:
        await asyncio.sleep(duration_s)
    finally:
        stop.set()
        for t in consumer_tasks:
            t.cancel()
        status_task.cancel()
        await asyncio.gather(*consumer_tasks, return_exceptions=True)
        await asyncio.gather(status_task, return_exceptions=True)

    for adapter in adapters:
        await adapter.close()

    log("SOAK_SUMMARY")
    for ex in tick_counts:
        log(f"{ex}: {tick_counts[ex]} ticks")

    end_ms = _now_ms()
    for ex, count in tick_counts.items():
        if count <= 0:
            raise SystemExit(f"FAIL: no ticks received from {ex}")
        age_s = (end_ms - last_tick_ms[ex]) / 1000.0 if last_tick_ms[ex] else 1e9
        if age_s > stale_threshold_s:
            raise SystemExit(
                f"FAIL: {ex} appears stale (last tick age {age_s:.1f}s > {stale_threshold_s:.1f}s)"
            )

    log("SOAK_RESULT OK")


if __name__ == "__main__":
    asyncio.run(main())
