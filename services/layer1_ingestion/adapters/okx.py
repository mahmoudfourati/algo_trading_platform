"""OKX WebSocket adapter.

Connects to OKX public WS and normalizes ticker messages into NormalizedTick.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Iterable, Optional

import websockets

from shared.schemas import NormalizedTick

from .base import AdapterConfig, BaseWsAdapter


_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"


def _okx_symbol(symbol: str) -> str:
    # OKX uses BTC-USDT style symbols.
    return symbol.upper()


class OkxAdapter(BaseWsAdapter):
    def __init__(self, symbols: list[str]):
        super().__init__(AdapterConfig(exchange_id="okx", symbols=symbols))

    async def fetch_rest_snapshot(self, symbols: Iterable[str]) -> None:
        # Best-effort informational snapshot; not required for Phase 2 correctness.
        _ = list(symbols)

    async def _connect_and_stream(self) -> AsyncIterator[NormalizedTick]:
        subscribe = {
            "op": "subscribe",
            "args": [{"channel": "tickers", "instId": _okx_symbol(s)} for s in self.symbols],
        }

        async with websockets.connect(_WS_URL, ping_interval=None) as ws:
            await ws.send(json.dumps(subscribe))

            async def ping_loop() -> None:
                while True:
                    await asyncio.sleep(25)
                    try:
                        await ws.send(json.dumps({"op": "ping"}))
                    except Exception:
                        return

            ping_task = asyncio.create_task(ping_loop(), name="okx-ping")
            try:
                while True:
                    raw = await self._recv_with_heartbeat(ws, timeout_s=self._config.heartbeat_timeout_s)
                    received_ts = self._now_ms()
                    tick = self.parse_message(raw, received_timestamp_ms=received_ts)
                    if tick is None:
                        continue
                    yield tick
            finally:
                ping_task.cancel()
                await asyncio.gather(ping_task, return_exceptions=True)

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

        # Ignore pongs and subscription events.
        if msg.get("event") in {"subscribe", "pong"}:
            return None

        arg = msg.get("arg")
        data = msg.get("data")
        if not isinstance(arg, dict) or not isinstance(data, list) or not data:
            return None

        if arg.get("channel") != "tickers":
            return None

        row = data[0]
        if not isinstance(row, dict):
            return None

        last = row.get("last")
        if last in {None, ""}:
            return None

        bid = row.get("bidPx")
        ask = row.get("askPx")
        ts = row.get("ts")
        if bid in {None, ""} or ask in {None, ""} or ts in {None, ""}:
            return None

        symbol = str(row.get("instId") or arg.get("instId") or "").upper()
        if not symbol:
            return None

        vol = row.get("vol24h") or row.get("volCcy24h") or 0.0

        return NormalizedTick(
            exchange_id="okx",
            symbol=symbol,
            bid=float(bid),
            ask=float(ask),
            last_price=float(last),
            volume_24h=float(vol),
            exchange_timestamp_ms=int(ts),
            received_timestamp_ms=received_timestamp_ms,
            sequence_id=None,
        )
