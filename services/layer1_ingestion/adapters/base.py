"""Base WebSocket adapter primitives.

Provides reconnection/backoff/heartbeat scaffolding and non-fatal TLS verification.
"""

from __future__ import annotations

import asyncio
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Iterable, Optional

import httpx

from shared.audit import emit_audit_event
from shared.schemas import NormalizedTick
from shared.tls_pinning import verify_spki_pin, days_until_cert_expiry, pins_path_from_env
from shared.tls_health_registry import get_tls_health_registry
from pathlib import Path


class HeartbeatTimeout(Exception):
    pass


@dataclass(frozen=True)
class AdapterConfig:
    exchange_id: str
    symbols: list[str]
    heartbeat_timeout_s: float = 5.0
    backoff_initial_s: float = 1.0
    backoff_max_s: float = 30.0


class BaseWsAdapter(ABC):
    def __init__(self, config: AdapterConfig):
        self._config = config
        self._http = httpx.AsyncClient(timeout=10.0)
        self._pins_path = pins_path_from_env(Path("config") / "tls_pins.json")
        self._tls_registry = get_tls_health_registry()

    @property
    def exchange_id(self) -> str:
        return self._config.exchange_id

    @property
    def symbols(self) -> list[str]:
        return list(self._config.symbols)

    @property
    def tls_ok(self) -> bool:
        """True if the most recent TLS pin check passed for this adapter."""
        return self._tls_registry.is_healthy(self.exchange_id)

    async def close(self) -> None:
        await self._http.aclose()

    async def run_forever(self) -> AsyncIterator[NormalizedTick]:
        backoff = self._config.backoff_initial_s
        first = True
        while True:
            try:
                if not first:
                    await self._fetch_rest_snapshot_safe()
                first = False

                # Successful (re)connect: reset backoff.
                backoff = self._config.backoff_initial_s

                # NON-FATAL TLS certificate pinning check before WS connect.
                # Failures are converted to trust degradation rather than crashes.
                tls_success, tls_reason = verify_spki_pin(
                    exchange_id=self.exchange_id,
                    pins_path=self._pins_path,
                    timeout=5.0
                )
                
                if tls_success:
                    self._tls_registry.mark_healthy(self.exchange_id)
                    emit_audit_event(
                        "adapter_tls_pin_verified",
                        source=self.exchange_id,
                        payload={"status": "ok"}
                    )
                else:
                    self._tls_registry.mark_unhealthy(self.exchange_id, reason=tls_reason)
                    emit_audit_event(
                        "adapter_tls_pin_failed",
                        source=self.exchange_id,
                        payload={
                            "reason": tls_reason,
                            "pins_path": str(self._pins_path),
                            "action": "continuing_with_degraded_trust"
                        },
                    )
                    # CRITICAL: Do NOT raise — continue operating with degraded trust
                
                # Expiry warning (non-fatal, best-effort)
                try:
                    from shared.tls_pinning import load_spki_pins
                    pin_cfg = load_spki_pins(self._pins_path).get(self.exchange_id)
                    if pin_cfg is not None:
                        days = days_until_cert_expiry(pin_cfg.host, pin_cfg.port, timeout=5.0)
                        if 0 < days <= 30:
                            emit_audit_event(
                                "adapter_tls_cert_expiry_warning",
                                source=self.exchange_id,
                                payload={"days_until_expiry": days, "host": pin_cfg.host, "port": pin_cfg.port},
                            )
                except Exception:
                    pass  # Expiry check is best-effort only
                
                emit_audit_event("adapter_connect", source=self.exchange_id, payload={"symbols": self.symbols})
                async for tick in self._connect_and_stream():
                    # Stamp the current TLS health onto every outgoing tick so the
                    # validated service can read the real result without side-channels.
                    current_tls_ok = self._tls_registry.is_healthy(self.exchange_id)
                    if tick.tls_ok != current_tls_ok:
                        tick = tick.model_copy(update={"tls_ok": current_tls_ok})
                    yield tick
                # If stream ends without exception, treat as disconnect.
                raise ConnectionError("WebSocket stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                emit_audit_event(
                    "adapter_disconnect",
                    source=self.exchange_id,
                    payload={"error": repr(exc), "backoff_s": backoff},
                )
                jitter = random.uniform(0.0, 0.25)
                await asyncio.sleep(min(self._config.backoff_max_s, backoff) + jitter)
                backoff = min(self._config.backoff_max_s, backoff * 2.0)

    async def _fetch_rest_snapshot_safe(self) -> None:
        try:
            emit_audit_event("adapter_rest_snapshot", source=self.exchange_id, payload={"symbols": self.symbols})
            await self.fetch_rest_snapshot(self.symbols)
        except Exception as exc:  # noqa: BLE001
            emit_audit_event(
                "adapter_rest_snapshot_failed",
                source=self.exchange_id,
                payload={"error": repr(exc)},
            )

    async def _recv_with_heartbeat(self, ws, *, timeout_s: float):
        """Receive the next message while enforcing a 5s liveness heartbeat.

        Blueprint requirement: a 5-second heartbeat timeout triggers a reconnect.

        Important nuance: some exchanges may not emit ticker messages every <5s.
        So we treat the heartbeat as a ping/pong liveness check, not a 'must receive tick'.
        """

        while True:
            try:
                return await asyncio.wait_for(ws.recv(), timeout=timeout_s)
            except TimeoutError:
                try:
                    pong_waiter = await ws.ping()
                    await asyncio.wait_for(pong_waiter, timeout=timeout_s)
                except Exception as exc:  # noqa: BLE001
                    raise HeartbeatTimeout(f"Ping/pong heartbeat failed within {timeout_s}s") from exc

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @abstractmethod
    async def fetch_rest_snapshot(self, symbols: Iterable[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def _connect_and_stream(self) -> AsyncIterator[NormalizedTick]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def parse_message(raw, *, received_timestamp_ms: int) -> Optional[NormalizedTick]:
        raise NotImplementedError
