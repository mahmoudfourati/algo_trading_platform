from __future__ import annotations

import asyncio
import json
import os
import signal
from typing import Iterable

from prometheus_client import Counter

from shared.schemas import NormalizedTick

from shared.metrics_http import start_metrics_http_server

from .adapters.binance import BinanceAdapter
from .adapters.coinbase import CoinbaseAdapter
from .adapters.kraken import KrakenAdapter
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
    return _parse_csv(os.getenv("EXCHANGES", "binance,coinbase,kraken"))


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

    symbols = _symbols()
    enabled = set(_exchanges())

    publisher = publisher_from_env()
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

    adapters = []
    if "binance" in enabled:
        adapters.append(BinanceAdapter(symbols))
    if "coinbase" in enabled:
        adapters.append(CoinbaseAdapter(symbols))
    if "kraken" in enabled:
        adapters.append(KrakenAdapter(symbols))

    async with asyncio.TaskGroup() as tg:
        for ad in adapters:
            if publisher:
                tg.create_task(_print_and_publish_ticks(ad.exchange_id, ad.run_forever(), stop, publisher))
            else:
                tg.create_task(_print_ticks(ad.exchange_id, ad.run_forever(), stop))
        await stop.wait()

    for ad in adapters:
        await ad.close()

    if publisher:
        publisher.stop()


if __name__ == "__main__":
    asyncio.run(main())
