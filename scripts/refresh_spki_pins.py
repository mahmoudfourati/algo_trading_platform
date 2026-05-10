"""Refresh SPKI pins (production-grade).

Fetches the current SubjectPublicKeyInfo (SPKI) SHA-256 hash for each configured
exchange and writes it back to config/tls_pins.json.

SPKI pinning is more resilient than leaf certificate pinning because it survives
certificate renewals as long as the same public key is reused.

Usage:
    .\.venv\Scripts\python scripts\refresh_spki_pins.py
    .\.venv\Scripts\python scripts\refresh_spki_pins.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.tls_pinning import fetch_spki_sha256, TlsPinningError  # noqa: E402

_PINS_PATH = _REPO_ROOT / "config" / "tls_pins.json"

_EXCHANGES = {
    "binance":  {"host": "stream.binance.com",          "port": 9443},
    "coinbase": {"host": "ws-feed.exchange.coinbase.com","port": 443},
    "kraken":   {"host": "ws.kraken.com",               "port": 443},
    "okx":      {"host": "ws.okx.com",                  "port": 8443},
    "bybit":    {"host": "stream.bybit.com",            "port": 443},
}


def main() -> None:
    p = argparse.ArgumentParser(description="Refresh SPKI pins for all exchanges")
    p.add_argument("--dry-run", action="store_true", help="Print SPKI hashes without writing the file")
    args = p.parse_args()

    result: dict = {}
    errors: list[str] = []

    for exchange_id, cfg in _EXCHANGES.items():
        host, port = cfg["host"], cfg["port"]
        print(f"  {exchange_id}: connecting to {host}:{port} ...", end=" ", flush=True)
        try:
            spki_hash = fetch_spki_sha256(host, port, timeout=10.0)
            print(spki_hash)
            result[exchange_id] = {"host": host, "port": port, "spki_sha256": spki_hash}
        except TlsPinningError as exc:
            print(f"ERROR: {exc}")
            errors.append(f"{exchange_id}: {exc}")
        except Exception as exc:
            print(f"UNEXPECTED ERROR: {exc}")
            errors.append(f"{exchange_id}: {exc}")

    if errors:
        print("\nFailed to fetch SPKI hashes for:")
        for e in errors:
            print(f"  {e}")
        if not result:
            sys.exit(1)

    if args.dry_run:
        print("\n[dry-run] Would write:")
        print(json.dumps(result, indent=2))
        return

    _PINS_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {len(result)} SPKI pin(s) to {_PINS_PATH}")

    if errors:
        print("WARNING: some exchanges failed — their pins were not updated.")
        sys.exit(1)


if __name__ == "__main__":
    main()
