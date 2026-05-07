"""Compare two metrics json files and print a compact delta summary."""
from __future__ import annotations
import json
import sys
from pathlib import Path

KEYS = [
    "gross_pnl",
    "net_pnl",
    "sharpe",
    "max_drawdown",
    "win_rate",
    "num_trades",
    "avg_trade_duration_s",
    "risk_approved_orders",
    "risk_rejected_orders",
    "risk_reduced_ticks",
    "risk_halted_ticks",
    "injected_anomalies",
    "detected_anomalies",
    "false_positives",
    "end_to_end_latency_ms",
]


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def delta(a, b):
    try:
        return round(float(b) - float(a), 6)
    except Exception:
        return None


def compare(base_path: str, live_path: str) -> None:
    base = load(base_path)
    live = load(live_path)
    print(f"Baseline: {base_path}")
    print(f"Live:     {live_path}\n")
    for k in KEYS:
        a = base.get(k, 0)
        b = live.get(k, 0)
        print(f"{k:30} baseline={a:12} live={b:12} delta={delta(a,b):8}")
    def rate(m):
        return (m.get("detected_anomalies", 0) / m.get("injected_anomalies", 1)) if m.get("injected_anomalies", 0) > 0 else 0
    print("\nDetection rate: baseline={:.2%} live={:.2%}".format(rate(base), rate(live)))


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python tools/compare_runs.py baseline_metrics.json live_metrics.json")
        sys.exit(2)
    compare(sys.argv[1], sys.argv[2])
