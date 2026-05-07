<!-- Purpose: Runbook and instructions for deterministic backtest and live soak runs -->

# Test Runs

This document describes how to run the deterministic backtest and the live soak, and where artifacts are stored.

- Backtest (deterministic): `scripts/run_backtest.sh` or `scripts/run_backtest.ps1`
- Live soak (testnet): `scripts/run_live_soak.sh` or `scripts/run_live_soak.ps1`

Outputs are written to `artifacts/test_runs/<tag>/` and include `metrics.json`, `per_trade_ledger.csv`, `reconciliation_report.json`, `report.html`, and archived logs/metrics.
