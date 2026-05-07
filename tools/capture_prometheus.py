"""Scrape a list of Prometheus /metrics endpoints and save each output to a folder.

Usage:
    python tools/capture_prometheus.py out_dir endpoint1 endpoint2 ...
"""
from __future__ import annotations
import sys
import requests
from pathlib import Path
from datetime import datetime


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/capture_prometheus.py out_dir endpoint1 [endpoint2 ...]")
        return 2
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    endpoints = sys.argv[2:]
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for i, ep in enumerate(endpoints, start=1):
        try:
            r = requests.get(ep, timeout=10)
            fname = out_dir / f"metrics_{i}_{ts}.txt"
            fname.write_text(r.text, encoding="utf-8")
            print(f"wrote {fname}")
        except Exception as e:
            print(f"failed to fetch {ep}: {e}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
