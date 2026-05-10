"""Refresh TLS pins.

Fetches the current leaf-certificate SHA-256 fingerprint for each configured
exchange and writes it back to config/tls_pins.json.

Run this whenever a certificate rotation is expected or after a pin-mismatch
audit event appears in the logs.

Usage:
    .\.venv\Scripts\python scripts\refresh_tls_pins.py
    .\.venv\Scripts\python scripts\refresh_tls_pins.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.tls_pinning import sha256_fingerprint_for_server  # noqa: E402

_PINS_PATH = _REPO_ROOT / "config" / "tls_pins.json"

_EXCHANGES = {
    "binance":  {"host": "stream.binance.com",          "port": 9443},
    "coinbase": {"host": "ws-feed.exchange.coinbase.com","port": 443},
    "kraken":   {"host": "ws.kraken.com",               "port": 443},
    "okx":      {"host": "ws.okx.com",                  "port": 8443},
    "bybit":    {"host": "stream.bybit.com",            "port": 443},
}


def main() -> None:
    p = argparse.ArgumentParser(description="Refresh TLS pins for all exchanges")
    p.add_argument("--dry-run", action="store_true", help="Print fingerprints without writing the file")
    args = p.parse_args()

    result: dict = {}
    errors: list[str] = []

    for exchange_id, cfg in _EXCHANGES.items():
        host, port = cfg["host"], cfg["port"]
        print(f"  {exchange_id}: connecting to {host}:{port} ...", end=" ", flush=True)
        try:
            fp = sha256_fingerprint_for_server(host, port)
            print(fp)
            result[exchange_id] = {"host": host, "port": port, "sha256_fingerprint": fp}
        except Exception as exc:
            print(f"ERROR: {exc}")
            errors.append(f"{exchange_id}: {exc}")

    if errors:
        print("\nFailed to fetch fingerprints for:")
        for e in errors:
            print(f"  {e}")
        if not result:
            sys.exit(1)

    if args.dry_run:
        print("\n[dry-run] Would write:")
        print(json.dumps(result, indent=2))
        return

    _PINS_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {len(result)} pin(s) to {_PINS_PATH}")

    if errors:
        print("WARNING: some exchanges failed — their pins were not updated.")
        sys.exit(1)


if __name__ == "__main__":
    main()
