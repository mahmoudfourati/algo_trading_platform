"""Unit tests for tools/compare_runs.py and tools/verify_run.py (basic smoke checks)."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
import subprocess


def test_compare_runs_smoke():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "base.json"
        live = Path(td) / "live.json"
        base.write_text(json.dumps({"net_pnl": 1.0, "detected_anomalies": 1, "injected_anomalies": 1}))
        live.write_text(json.dumps({"net_pnl": 2.0, "detected_anomalies": 1, "injected_anomalies": 1}))
        out = subprocess.check_output(["python", "tools/compare_runs.py", str(base), str(live)], text=True)
        assert "Baseline:" in out


def test_verify_run_smoke():
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td) / "run"
        run_dir.mkdir()
        # create minimal metrics.json and per_trade_ledger.csv
        (run_dir / "metrics.json").write_text(json.dumps({}))
        ledger = run_dir / "per_trade_ledger.csv"
        ledger.write_text("trade_id,client_order_id,signal_ts,submit_ts,ack_ts,first_fill_ts,last_fill_ts,fill_price,fill_fraction,side,size_pct,fee,slippage_pct,final_state,exit_reason,net_pnl\n")
        # create a simple reconciliation report
        (run_dir / "reconciliation_report.json").write_text(json.dumps([]))
        res = subprocess.run(["python", "tools/verify_run.py", str(run_dir)])
        assert res.returncode == 0
