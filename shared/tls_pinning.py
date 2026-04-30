"""TLS pinning utilities.

Loads expected leaf-certificate SHA-256 fingerprints and verifies remote servers.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class TlsPinningError(RuntimeError):
    pass


def _normalize_fingerprint(value: str) -> str:
    v = value.strip().lower().replace(":", "")
    if any(c not in "0123456789abcdef" for c in v):
        raise ValueError("Fingerprint must be hex")
    if len(v) != 64:
        raise ValueError("SHA-256 fingerprint must be 64 hex chars")
    return v


def sha256_fingerprint_for_server(host: str, port: int, *, server_hostname: Optional[str] = None) -> str:
    """Return SHA-256 fingerprint (hex, no colons) for the server's leaf certificate."""

    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    sni = server_hostname or host
    with socket.create_connection((host, port), timeout=10.0) as sock:
        with context.wrap_socket(sock, server_hostname=sni) as ssock:
            der = ssock.getpeercert(binary_form=True)
    return hashlib.sha256(der).hexdigest()


def days_until_cert_expiry(host: str, port: int, *, server_hostname: Optional[str] = None) -> int:
    """Return whole days until leaf cert expiry (UTC)."""

    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    sni = server_hostname or host
    with socket.create_connection((host, port), timeout=10.0) as sock:
        with context.wrap_socket(sock, server_hostname=sni) as ssock:
            cert = ssock.getpeercert()
    not_after = cert.get("notAfter")
    if not not_after:
        raise RuntimeError("Certificate notAfter missing")

    # Example format: 'Apr 12 12:00:00 2026 GMT'
    expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = expiry - now
    return int(delta.total_seconds() // 86400)


@dataclass(frozen=True)
class Pin:
    host: str
    port: int
    sha256_fingerprint: str


def load_pins(path: Path) -> dict[str, Pin]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, Pin] = {}
    for exchange_id, cfg in data.items():
        out[exchange_id] = Pin(
            host=str(cfg["host"]),
            port=int(cfg["port"]),
            sha256_fingerprint=_normalize_fingerprint(str(cfg["sha256_fingerprint"])),
        )
    return out


def verify_pin_or_raise(*, exchange_id: str, pins_path: Path) -> None:
    pins = load_pins(pins_path)
    if exchange_id not in pins:
        raise TlsPinningError(f"No TLS pin configured for {exchange_id}")

    pin = pins[exchange_id]
    actual = sha256_fingerprint_for_server(pin.host, pin.port)
    if actual != pin.sha256_fingerprint:
        raise TlsPinningError(
            f"TLS pin mismatch for {exchange_id}: expected={pin.sha256_fingerprint} actual={actual}"
        )


def pins_path_from_env(default: Path) -> Path:
    raw = os.getenv("TLS_PINS_PATH")
    return Path(raw) if raw else default
