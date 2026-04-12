from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncIterator, Iterable, Optional

import websockets

from shared.schemas import NormalizedTick

from .base import AdapterConfig, BaseWsAdapter


_WS_URL = "wss://ws-feed.exchange.coinbase.com"
_REST_BOOK = "https://api.exchange.coinbase.com/products/{product_id}/book"


def _coinbase_product(symbol: str) -> str:
    # "BTC-USDT" is already Coinbase format.
    return symbol.upper()


def _parse_iso8601_ms(ts: str) -> int:
    # Example: "2020-01-01T00:00:00.123456Z"
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    return int(dt.timestamp() * 1000)


class CoinbaseAdapter(BaseWsAdapter):
    def __init__(self, symbols: list[str]):
        super().__init__(AdapterConfig(exchange_id="coinbase", symbols=symbols))

    async def fetch_rest_snapshot(self, symbols: Iterable[str]) -> None:
        # level=1 provides best bid/ask.
        for sym in symbols:
            url = _REST_BOOK.format(product_id=_coinbase_product(sym))
            r = await self._http.get(url, params={"level": 1})
            r.raise_for_status()
            data = r.json()
            best_bid = float(data["bids"][0][0]) if data.get("bids") else None
            best_ask = float(data["asks"][0][0]) if data.get("asks") else None
            _ = (best_bid, best_ask)

    async def _connect_and_stream(self) -> AsyncIterator[NormalizedTick]:
        subscribe = {
            "type": "subscribe",
            "product_ids": [_coinbase_product(s) for s in self.symbols],
            "channels": ["ticker"],
        }

        async with websockets.connect(_WS_URL, ping_interval=None) as ws:
            await ws.send(json.dumps(subscribe))
            while True:
                raw = await self._recv_with_heartbeat(ws, timeout_s=self._config.heartbeat_timeout_s)
                received_ts = self._now_ms()
                tick = self.parse_message(raw, received_timestamp_ms=received_ts)
                if tick is None:
                    continue
                yield tick

    @staticmethod
    def parse_message(raw, *, received_timestamp_ms: int) -> Optional[NormalizedTick]:
        if isinstance(raw, str):
            msg = json.loads(raw)
        elif isinstance(raw, (bytes, bytearray)):
            msg = json.loads(raw.decode("utf-8"))
        elif isinstance(raw, dict):
            msg = raw
        else:
            return None

        if msg.get("type") != "ticker":
            return None

        required = ("product_id", "best_bid", "best_ask", "price", "volume_24h", "time")
        if not all(k in msg for k in required):
            return None

        seq = msg.get("sequence")
        sequence_id = int(seq) if seq is not None else None
        return NormalizedTick(
            exchange_id="coinbase",
            symbol=str(msg["product_id"]).upper(),
            bid=float(msg["best_bid"]),
            ask=float(msg["best_ask"]),
            last_price=float(msg["price"]),
            volume_24h=float(msg["volume_24h"]),
            exchange_timestamp_ms=_parse_iso8601_ms(str(msg["time"])),
            received_timestamp_ms=received_timestamp_ms,
            sequence_id=sequence_id,
        )
