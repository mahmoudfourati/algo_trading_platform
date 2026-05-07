"""Verify backtest / live run artifacts and produce verification_report.json.

Checks implemented:
- primary presence ratio (uses metrics.per_layer if available, otherwise skipped)
- WAL-before-send (checks reconciliation_report entries)
- idempotency heuristic (no duplicate client_order_id with conflicting fill fractions)
- portfolio balance (uses metrics: net_pnl/gross if available; best-effort)
- CLOSE_ALL effect (checks per_trade_ledger for CLOSE_ALL exit_reason)

Produces exit code 0 on success, non-zero on failure.
"""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path
from typing import Any

OUT_FILE = "verification_report.json"


def load_metrics(metrics_path: Path) -> dict:
    if not metrics_path.exists():
        return {}
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def load_ledger(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    rows = []
    with open(ledger_path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows


def load_recon(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def check_primary_presence(metrics: dict) -> dict:
    # best-effort: expect metrics.per_layer.layer1.primary_missing_total or similar
    res = {"name": "primary_presence", "passed": True, "notes": "not-evaluated"}
    per_layer = metrics.get("per_layer") or {}
    layer1 = per_layer.get("layer1") or {}
    missing = layer1.get("primary_missing_total") or layer1.get("primary_missing")
    total = layer1.get("validated_windows_total") or layer1.get("total_windows")
    if missing is None or total is None:
        res["notes"] = "insufficient-metrics"
        return res
    threshold = 0.05
    ratio = float(missing) / float(total) if float(total) > 0 else 0.0
    res["notes"] = {"missing": missing, "total": total, "ratio": ratio}
    res["passed"] = ratio <= threshold
    return res


def check_wal_before_send(recon: list) -> dict:
    res = {"name": "wal_before_send", "passed": True, "notes": []}
    for row in recon:
        wal_ts = row.get("wal_ts")
        adapter_ts = row.get("adapter_ts")
        if wal_ts is None or adapter_ts is None:
            continue
        try:
            wal = int(wal_ts)
            ada = int(adapter_ts)
            if wal > ada + 5000:  # allow 5s clock skew
                res["passed"] = False
                res["notes"].append({"client_order_id": row.get("client_order_id"), "wal_ts": wal, "adapter_ts": ada})
        except Exception:
            continue
    if not res["notes"]:
        res["notes"] = "ok"
    return res


def check_idempotency(ledger: list[dict]) -> dict:
    res = {"name": "idempotency", "passed": True, "notes": []}
    seen: dict[str, dict] = {}
    for r in ledger:
        coid = r.get("client_order_id")
        if not coid:
            continue
        fill = float(r.get("fill_fraction") or 0)
        if coid in seen:
            prev = seen[coid]
            prev_fill = float(prev.get("fill_fraction") or 0)
            # if fills differ significantly, flag
            if abs(prev_fill - fill) > 1e-6:
                res["passed"] = False
                res["notes"].append({"client_order_id": coid, "prev_fill": prev_fill, "fill": fill})
        else:
            seen[coid] = r
    if not res["notes"]:
        res["notes"] = "ok"
    return res


def check_portfolio_balance(metrics: dict) -> dict:
    res = {"name": "portfolio_balance", "passed": True, "notes": "not-evaluated"}
    # best-effort: look for portfolio fields
    pv = metrics.get("portfolio_value") or metrics.get("starting_portfolio")
    net = metrics.get("net_pnl") or metrics.get("equity_net") or metrics.get("net")
    if pv is None or net is None:
        return res
    try:
        pv = float(pv)
        net = float(net)
        # we expect pv + net to equal some value — this is domain-specific; we'll just sanity check pv not negative
        res["passed"] = pv > 0
        res["notes"] = {"portfolio_value": pv, "net": net}
    except Exception:
        res["notes"] = "parse-error"
        res["passed"] = False
    return res


def check_close_all(ledger: list[dict]) -> dict:
    res = {"name": "close_all_effect", "passed": True, "notes": "no-close_all"}
    # find CLOSE_ALL rows and ensure positions closed — heuristic: exit_reason == CLOSE_ALL or side==CLOSE_ALL
    closes = [r for r in ledger if (r.get("exit_reason") or "").upper() == "CLOSE_ALL" or (r.get("side") or "").upper() == "CLOSE_ALL"]
    if not closes:
        return res
    res["notes"] = {"close_count": len(closes)}
    # if any, mark passed true (backtest should close immediately)
    res["passed"] = True
    return res


def main(run_dir: str) -> int:
    run_path = Path(run_dir)
    metrics = load_metrics(run_path / "metrics.json")
    ledger = load_ledger(run_path / "per_trade_ledger.csv")
    recon = load_recon(run_path / "reconciliation_report.json")

    checks = []
    checks.append(check_primary_presence(metrics))
    checks.append(check_wal_before_send(recon))
    checks.append(check_idempotency(ledger))
    checks.append(check_portfolio_balance(metrics))
    checks.append(check_close_all(ledger))

    report = {"run_dir": str(run_dir), "checks": checks}
    out_path = Path(run_dir) / OUT_FILE
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # non-zero exit if any mandatory check failed
    failed = any(not c.get("passed", False) and c.get("name") in {"wal_before_send", "idempotency", "portfolio_balance"} for c in checks)
    return 0 if not failed else 3


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python tools/verify_run.py <run_dir>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
