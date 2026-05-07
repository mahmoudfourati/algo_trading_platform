"""Bybit WebSocket adapter.

Connects to Bybit public WS and normalizes ticker messages into NormalizedTick.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Iterable, Optional

import websockets

from shared.schemas import NormalizedTick

from .base import AdapterConfig, BaseWsAdapter


# NOTE: The spot ticker stream does not include best bid/ask.
# We use the linear stream for bid/ask/last to align with NormalizedTick.
_WS_URL = "wss://stream.bybit.com/v5/public/linear"


def _to_bybit_symbol(symbol: str) -> str:
    """'BTC-USDT' → 'BTCUSDT'"""

    return symbol.replace("-", "").upper()


def _from_bybit_symbol(symbol: str) -> str:
    """'BTCUSDT' → 'BTC-USDT' (assumes 4-char quote: USDT)."""

    s = symbol.upper()
    if len(s) <= 4:
        return s
    return s[:-4] + "-" + s[-4:]


class BybitAdapter(BaseWsAdapter):
    def __init__(self, symbols: list[str]):
        super().__init__(AdapterConfig(exchange_id="bybit", symbols=symbols))
        self._state_by_symbol: dict[str, dict[str, Any]] = {}

    async def fetch_rest_snapshot(self, symbols: Iterable[str]) -> None:
        _ = list(symbols)

    async def _connect_and_stream(self) -> AsyncIterator[NormalizedTick]:
        subscribe = {
            "op": "subscribe",
            "args": [f"tickers.{_to_bybit_symbol(s)}" for s in self.symbols],
        }

        async with websockets.connect(_WS_URL, ping_interval=None) as ws:
            await ws.send(json.dumps(subscribe))

            async def ping_loop() -> None:
                while True:
                    await asyncio.sleep(20)
                    try:
                        await ws.send(json.dumps({"op": "ping"}))
                    except Exception:
                        return

            ping_task = asyncio.create_task(ping_loop(), name="bybit-ping")
            try:
                while True:
                    raw = await self._recv_with_heartbeat(ws, timeout_s=self._config.heartbeat_timeout_s)
                    received_ts = self._now_ms()
                    tick = self._parse_message_with_state(raw, received_timestamp_ms=received_ts)
                    if tick is None:
                        continue
                    yield tick
            finally:
                ping_task.cancel()
                await asyncio.gather(ping_task, return_exceptions=True)

    def _parse_message_with_state(self, raw, *, received_timestamp_ms: int) -> Optional[NormalizedTick]:
        msg = self._coerce_message(raw)
        if msg is None:
            return None

        topic = msg.get("topic")
        if not isinstance(topic, str) or not topic.startswith("tickers."):
            return None

        data = msg.get("data")
        if isinstance(data, list):
            if not data:
                return None
            data = data[0]
        if not isinstance(data, dict):
            return None

        sym_raw = data.get("symbol")
        if not isinstance(sym_raw, str) or not sym_raw:
            return None

        state = self._state_by_symbol.setdefault(sym_raw, {})

        # Merge partial "delta" fields into the last known snapshot.
        for key in ("lastPrice", "bid1Price", "ask1Price", "turnover24h", "volume24h"):
            val = data.get(key)
            if val not in (None, ""):
                state[key] = val

        ts = msg.get("ts")
        if ts is not None:
            state["ts"] = ts

        last = state.get("lastPrice")
        bid = state.get("bid1Price")
        ask = state.get("ask1Price")
        ts_final = state.get("ts")
        if last in (None, "") or bid in (None, "") or ask in (None, "") or ts_final is None:
            return None

        vol = state.get("turnover24h") or state.get("volume24h") or 0.0

        return NormalizedTick(
            exchange_id="bybit",
            symbol=_from_bybit_symbol(sym_raw),
            bid=float(bid),
            ask=float(ask),
            last_price=float(last),
            volume_24h=float(vol),
            exchange_timestamp_ms=int(ts_final),
            received_timestamp_ms=received_timestamp_ms,
            sequence_id=None,
        )

    @staticmethod
    def _coerce_message(raw) -> Optional[dict[str, Any]]:
        if isinstance(raw, str):
            return json.loads(raw)
        if isinstance(raw, (bytes, bytearray)):
            return json.loads(raw.decode("utf-8"))
        if isinstance(raw, dict):
            return raw
        return None

    @staticmethod
    def parse_message(raw, *, received_timestamp_ms: int) -> Optional[NormalizedTick]:
        msg = BybitAdapter._coerce_message(raw)
        if msg is None:
            return None

        topic = msg.get("topic")
        if not isinstance(topic, str) or not topic.startswith("tickers."):
            return None

        data = msg.get("data")
        if isinstance(data, list):
            if not data:
                return None
            data = data[0]
        if not isinstance(data, dict):
            return None

        last = data.get("lastPrice")
        bid = data.get("bid1Price")
        ask = data.get("ask1Price")
        if last in {None, ""} or bid in {None, ""} or ask in {None, ""}:
            return None

        ts = msg.get("ts")
        if ts is None:
            return None

        sym_raw = data.get("symbol")
        if not isinstance(sym_raw, str) or not sym_raw:
            return None

        vol = data.get("turnover24h") or data.get("volume24h") or 0.0

        return NormalizedTick(
            exchange_id="bybit",
            symbol=_from_bybit_symbol(sym_raw),
            bid=float(bid),
            ask=float(ask),
            last_price=float(last),
            volume_24h=float(vol),
            exchange_timestamp_ms=int(ts),
            received_timestamp_ms=received_timestamp_ms,
            sequence_id=None,
        )
