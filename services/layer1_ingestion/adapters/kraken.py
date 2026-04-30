"""Kraken WebSocket adapter.

Connects to Kraken feed and normalizes ticker messages into NormalizedTick.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, Iterable, Optional

import websockets

from shared.schemas import NormalizedTick

from .base import AdapterConfig, BaseWsAdapter


_WS_URL = "wss://ws.kraken.com"
_REST_DEPTH = "https://api.kraken.com/0/public/Depth"


def _kraken_pair(symbol: str) -> str:
    # Kraken commonly uses XBT for BTC.
    s = symbol.upper().replace("-", "/")
    if s.startswith("BTC/"):
        s = s.replace("BTC/", "XBT/")
    return s


def _kraken_rest_pair(symbol: str) -> str:
    # REST expects e.g. XBTUSDT
    return _kraken_pair(symbol).replace("/", "")


class KrakenAdapter(BaseWsAdapter):
    def __init__(self, symbols: list[str]):
        super().__init__(AdapterConfig(exchange_id="kraken", symbols=symbols))

    async def fetch_rest_snapshot(self, symbols: Iterable[str]) -> None:
        for sym in symbols:
            params = {"pair": _kraken_rest_pair(sym), "count": 1}
            r = await self._http.get(_REST_DEPTH, params=params)
            r.raise_for_status()
            data = r.json()
            # Snapshot is informational in Phase 2.1.
            _ = data.get("result")

    async def _connect_and_stream(self) -> AsyncIterator[NormalizedTick]:
        subscribe = {
            "event": "subscribe",
            "pair": [_kraken_pair(s) for s in self.symbols],
            "subscription": {"name": "ticker"},
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
        else:
            msg = raw

        # Ignore non-data events.
        if isinstance(msg, dict):
            return None
        if not isinstance(msg, list) or len(msg) < 4:
            return None

        # Data format: [channelID, data, channelName, pair]
        data = msg[1]
        channel = msg[2]
        pair = msg[3]
        if channel != "ticker" or not isinstance(data, dict):
            return None

        if not all(k in data for k in ("a", "b", "c", "v")):
            return None

        ask = float(data["a"][0])
        bid = float(data["b"][0])
        last = float(data["c"][0])
        vol_24h = float(data["v"][1]) if len(data["v"]) > 1 else float(data["v"][0])

        # Pair example: "XBT/USDT" -> "BTC-USDT"
        norm_pair = str(pair).upper().replace("XBT", "BTC").replace("/", "-")
        return NormalizedTick(
            exchange_id="kraken",
            symbol=norm_pair,
            bid=bid,
            ask=ask,
            last_price=last,
            volume_24h=vol_24h,
            exchange_timestamp_ms=received_timestamp_ms,
            received_timestamp_ms=received_timestamp_ms,
            sequence_id=None,
        )
