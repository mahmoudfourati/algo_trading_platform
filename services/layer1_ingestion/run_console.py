"""Layer 1 ingestion service entrypoint.

Runs exchange adapters, emits Prometheus metrics, and publishes raw ticks to Kafka.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import signal
from typing import Iterable

from prometheus_client import Counter

from shared.schemas import NormalizedTick

from shared.metrics_http import start_metrics_http_server
from shared.service_health import mark_service_healthy

from .adapters.binance import BinanceAdapter
from .adapters.bybit import BybitAdapter
from .adapters.coinbase import CoinbaseAdapter
from .adapters.kraken import KrakenAdapter
from .adapters.okx import OkxAdapter
from .kafka_publisher import RawTickKafkaPublisher, publisher_from_env


_ticks_total = Counter(
    "layer1_ingestion_ticks_total",
    "Total normalized ticks observed by ingestion.",
    ["exchange"],
)

_published_total = Counter(
    "layer1_ingestion_published_total",
    "Total normalized ticks published to Kafka raw topic.",
    ["exchange"],
)


def _parse_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _symbols() -> list[str]:
    return _parse_csv(os.getenv("SYMBOLS", "BTC-USDT,ETH-USDT"))


def _exchanges() -> list[str]:
    return _parse_csv(os.getenv("EXCHANGES", "binance,bybit,coinbase,kraken,okx"))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Layer 1 ingestion console runner")
    p.add_argument("--symbols", default=None, help="Comma-separated symbols (overrides SYMBOLS env)")
    p.add_argument(
        "--sources",
        "--exchanges",
        dest="sources",
        default=None,
        help="Comma-separated exchanges (overrides EXCHANGES env)",
    )
    p.add_argument("--no-kafka", action="store_true", help="Disable Kafka publishing even if enabled via env")
    p.add_argument("--duration", type=int, default=0, help="Stop after N seconds (0 = run until Ctrl+C)")
    return p.parse_args()


async def _print_ticks(name: str, tick_iter, stop: asyncio.Event) -> None:
    async for tick in tick_iter:
        if stop.is_set():
            break
        _ticks_total.labels(exchange=name).inc()
        print(json.dumps(tick.model_dump(), separators=(",", ":"), sort_keys=True))


async def _print_and_publish_ticks(
    name: str,
    tick_iter,
    stop: asyncio.Event,
    publisher: RawTickKafkaPublisher,
) -> None:
    async for tick in tick_iter:
        if stop.is_set():
            break
        _ticks_total.labels(exchange=name).inc()
        print(json.dumps(tick.model_dump(), separators=(",", ":"), sort_keys=True))
        publisher.publish(tick)
        _published_total.labels(exchange=name).inc()


async def main() -> None:
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9101")))
    mark_service_healthy("layer1_ingestion", "layer1")

    args = _parse_args()
    symbols = _parse_csv(args.symbols) if args.symbols else _symbols()
    enabled = set(_parse_csv(args.sources)) if args.sources else set(_exchanges())

    publisher = None if args.no_kafka else publisher_from_env()
    if publisher:
        publisher.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows event loop may not support add_signal_handler for SIGTERM.
            pass

    async def stop_after_duration() -> None:
        if args.duration > 0:
            await asyncio.sleep(args.duration)
            stop.set()

    adapters = []
    if "binance" in enabled:
        adapters.append(BinanceAdapter(symbols))
    if "coinbase" in enabled:
        adapters.append(CoinbaseAdapter(symbols))
    if "kraken" in enabled:
        adapters.append(KrakenAdapter(symbols))
    if "okx" in enabled:
        adapters.append(OkxAdapter(symbols))
    if "bybit" in enabled:
        adapters.append(BybitAdapter(symbols))

    tick_tasks: list[asyncio.Task] = []
    duration_task = asyncio.create_task(stop_after_duration(), name="stop-after-duration")
    try:
        for ad in adapters:
            if publisher:
                tick_tasks.append(
                    asyncio.create_task(
                        _print_and_publish_ticks(ad.exchange_id, ad.run_forever(), stop, publisher),
                        name=f"print-publish-{ad.exchange_id}",
                    )
                )
            else:
                tick_tasks.append(
                    asyncio.create_task(
                        _print_ticks(ad.exchange_id, ad.run_forever(), stop),
                        name=f"print-{ad.exchange_id}",
                    )
                )

        await stop.wait()
    finally:
        duration_task.cancel()
        for t in tick_tasks:
            t.cancel()
        await asyncio.gather(duration_task, *tick_tasks, return_exceptions=True)

    for ad in adapters:
        await ad.close()

    if publisher:
        publisher.stop()


if __name__ == "__main__":
    asyncio.run(main())
