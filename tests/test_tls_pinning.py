"""Tests for TLS pinning helpers.

Validates mismatch refusal and configuration parsing behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.tls_pinning import TlsPinningError, verify_pin_or_raise


def test_tls_pinning_mismatch_refuses(monkeypatch, tmp_path: Path) -> None:
    pins = {
        "binance": {"host": "example.com", "port": 443, "sha256_fingerprint": "00" * 32},
    }
    path = tmp_path / "pins.json"
    path.write_text(json.dumps(pins), encoding="utf-8")

    # Force the computed fingerprint to something else.
    monkeypatch.setattr(
        "shared.tls_pinning.sha256_fingerprint_for_server",
        lambda host, port, server_hostname=None: "11" * 32,
    )

    with pytest.raises(TlsPinningError):
        verify_pin_or_raise(exchange_id="binance", pins_path=path)

