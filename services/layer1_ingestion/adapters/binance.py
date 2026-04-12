from __future__ import annotations

import json
from typing import AsyncIterator, Iterable, Optional

import httpx
import websockets

from shared.schemas import NormalizedTick

from .base import AdapterConfig, BaseWsAdapter


_WS_BASE = "wss://stream.binance.com:9443/ws"
_WS_COMBINED = "wss://stream.binance.com:9443/stream"
_REST_DEPTH = "https://api.binance.com/api/v3/depth"


def _binance_symbol(symbol: str) -> str:
    # "BTC-USDT" -> "BTCUSDT"
    return symbol.replace("-", "").upper()


class BinanceAdapter(BaseWsAdapter):
    def __init__(self, symbols: list[str]):
        super().__init__(AdapterConfig(exchange_id="binance", symbols=symbols))

    async def fetch_rest_snapshot(self, symbols: Iterable[str]) -> None:
        for sym in symbols:
            params = {"symbol": _binance_symbol(sym), "limit": 5}
            r = await self._http.get(_REST_DEPTH, params=params)
            r.raise_for_status()
            data = r.json()
            best_bid = float(data["bids"][0][0]) if data.get("bids") else None
            best_ask = float(data["asks"][0][0]) if data.get("asks") else None
            # Snapshot is informational in Phase 2.1.
            _ = (best_bid, best_ask)

    async def _connect_and_stream(self) -> AsyncIterator[NormalizedTick]:
        # Use 24hr ticker stream because it includes bid/ask/last/volume_24h.
        # Combined stream supports multiple symbols over a single WS:
        # wss://.../stream?streams=btcusdt@ticker/ethusdt@ticker
        streams = "/".join(f"{_binance_symbol(s).lower()}@ticker" for s in self.symbols)
        url = f"{_WS_COMBINED}?streams={streams}"
        async with websockets.connect(url, ping_interval=None) as ws:
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

        # Combined stream wrapper: {"stream": "btcusdt@ticker", "data": {...}}
        if isinstance(msg, dict) and "data" in msg and isinstance(msg["data"], dict):
            msg = msg["data"]

        if not all(k in msg for k in ("b", "a", "c", "v", "E", "s")):
            return None

        symbol = msg["s"].upper()
        # "BTCUSDT" -> "BTC-USDT"
        norm_symbol = symbol.replace("USDT", "-USDT") if symbol.endswith("USDT") else symbol
        return NormalizedTick(
            exchange_id="binance",
            symbol=norm_symbol,
            bid=float(msg["b"]),
            ask=float(msg["a"]),
            last_price=float(msg["c"]),
            volume_24h=float(msg["v"]),
            exchange_timestamp_ms=int(msg["E"]),
            received_timestamp_ms=received_timestamp_ms,
            sequence_id=None,
        )
