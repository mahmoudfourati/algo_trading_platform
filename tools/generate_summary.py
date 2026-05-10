"""Generate a human-friendly executive summary from backtest artifacts."""
from __future__ import annotations
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Any


def generate_summary(run_dir: str) -> str:
    run_path = Path(run_dir)
    metrics_file = run_path / "metrics.json"
    ledger_file = run_path / "per_trade_ledger.csv"
    recon_file = run_path / "reconciliation_report.json"
    config_file = run_path / "config_snapshot.json"
    
    if not metrics_file.exists():
        return f"ERROR: metrics.json not found in {run_dir}"
    
    metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    config = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    
    # read ledger
    trades = []
    if ledger_file.exists():
        with open(ledger_file, "r", encoding="utf-8") as f:
            trades = list(csv.DictReader(f))
    
    # read reconciliation
    recon = json.loads(recon_file.read_text(encoding="utf-8")) if recon_file.exists() else []
    
    # build summary
    lines = []
    lines.append("=" * 80)
    lines.append("BACKTEST EXECUTIVE SUMMARY")
    lines.append("=" * 80)
    lines.append("")
    
    # run info
    lines.append("RUN INFORMATION")
    lines.append(f"  Symbol:           {metrics.get('symbol', 'N/A')}")
    lines.append(f"  Scenario:         {metrics.get('scenario', 'N/A')}")
    lines.append(f"  Period:           {metrics.get('start_time', 'N/A')} to {metrics.get('end_time', 'N/A')}")
    lines.append(f"  Total ticks:      {metrics.get('total_ticks', 0):,}")
    lines.append("")
    
    # performance metrics
    lines.append("PERFORMANCE")
    lines.append(f"  Net PnL:          ${metrics.get('net_pnl', 0):.2f}")
    lines.append(f"  Gross PnL:        ${metrics.get('gross_pnl', 0):.2f}")
    lines.append(f"  Sharpe Ratio:     {metrics.get('sharpe_ratio', 0):.4f}")
    lines.append(f"  Max Drawdown:     {metrics.get('max_drawdown', 0):.4f}")
    lines.append(f"  Win Rate:         {metrics.get('win_rate', 0):.2%}")
    lines.append(f"  Permutation Test: p-value = {metrics.get('permutation_p_value', 1.0):.4f}")
    sig = "SIGNIFICANT" if metrics.get('permutation_p_value', 1.0) < 0.05 else "not significant"
    lines.append(f"                    ({sig})")
    lines.append("")

    # live-soak style Layer 1 checklist
    trust_stats = metrics.get('layer1_trust_statistics', {}) or {}
    soak_checklist = metrics.get('layer1_soak_checklist', {}) or {}
    if trust_stats:
        lines.append("LAYER 1 SOAK CHECKLIST")
        lines.append(f"  Trust score mean:   {trust_stats.get('mean', 0):.6f}")
        lines.append(f"  Trust score std:    {trust_stats.get('std', 0):.6f}")
        lines.append(f"  Trust score min/max:{trust_stats.get('min', 0):.6f} / {trust_stats.get('max', 0):.6f}")
        lines.append(f"  Trust p5/p95:       {trust_stats.get('p5', 0):.6f} / {trust_stats.get('p95', 0):.6f}")
        lines.append(f"  Trust range:        {trust_stats.get('range', 0):.6f}")
        lines.append("")

        def _check_line(label: str, key: str, threshold_hint: str) -> None:
            value = bool(soak_checklist.get(key, False))
            status = "PASS" if value else "FAIL"
            mark = "✓" if value else "✗"
            lines.append(f"  {mark} {label}: {status} ({threshold_hint})")

        _check_line("Trust std > 0", "trust_score_std_gt_zero", "> 0.0")
        _check_line("Trust range > 0.01", "trust_score_range_gt_001", "> 0.01")
        _check_line("Trust p95 - p5 > 0.01", "trust_score_p95_minus_p5_gt_001", "> 0.01")
        _check_line("T2 range > 0.01", "t2_range_gt_001", "> 0.01")
        _check_line("T3 range > 0.01", "t3_range_gt_001", "> 0.01")
        lines.append("")
    
    # layer metrics
    lines.append("LAYER STATISTICS")
    lines.append(f"  Layer 2 - Anomalies detected:   {metrics.get('detected_anomalies', 0)}")
    lines.append(f"  Layer 2 - False positives:      {metrics.get('false_positives', 0)}")
    lines.append(f"  Layer 2 - False positive rate:  {metrics.get('false_positive_rate', 0):.2%}")
    lines.append(f"  Layer 4 - Approved orders:      {metrics.get('risk_approved_orders', 0)}")
    lines.append(f"  Layer 4 - Rejected orders:      {metrics.get('risk_rejected_orders', 0)}")
    lines.append(f"  Layer 4 - Reduced state ticks:  {metrics.get('risk_reduced_ticks', 0)}")
    lines.append(f"  Layer 4 - Halted state ticks:   {metrics.get('risk_halted_ticks', 0)}")
    lines.append(f"  Circuit breaker state:         {(1.0 - metrics.get('normal_state_pct', 1.0)):.1%} degraded")
    lines.append("")
    
    # trading activity
    lines.append("TRADING ACTIVITY")
    lines.append(f"  Trades executed:  {len(trades)}")
    if trades:
        avg_fee = sum(float(t.get('fee', 0) or 0) for t in trades) / len(trades) if trades else 0
        avg_slippage = sum(float(t.get('slippage_pct', 0) or 0) for t in trades) / len(trades) if trades else 0
        lines.append(f"  Avg fee:          {avg_fee:.6f}")
        lines.append(f"  Avg slippage:     {avg_slippage:.4%}")
    else:
        lines.append(f"  (no trades executed)")
    lines.append("")
    
    # reconciliation
    lines.append("RECONCILIATION & WAL")
    unresolved = sum(1 for r in recon if not r.get('resolved', False))
    lines.append(f"  Total orders in WAL:  {len(recon)}")
    lines.append(f"  Unresolved:           {unresolved}")
    if unresolved > 0:
        lines.append("  STATUS: ⚠️  UNRESOLVED ORDERS DETECTED")
    else:
        lines.append("  STATUS: ✓ All orders reconciled")
    lines.append("")
    
    # pass/fail verdict
    lines.append("VERDICT")
    passed_checks = 0
    total_checks = 0
    
    # check 1: positive pnl or significant permutation test
    total_checks += 1
    if metrics.get('net_pnl', 0) > 0 or metrics.get('permutation_p_value', 1.0) < 0.05:
        lines.append("  ✓ PROFIT or SIGNIFICANCE: PASS")
        passed_checks += 1
    else:
        lines.append("  ✗ PROFIT or SIGNIFICANCE: FAIL (no profit + not significant)")
    
    # check 2: false positive rate acceptable
    total_checks += 1
    fp_rate = metrics.get('false_positive_rate', 0)
    if fp_rate < 0.02:
        lines.append(f"  ✓ FALSE POSITIVE RATE: PASS ({fp_rate:.2%} < 2%)")
        passed_checks += 1
    else:
        lines.append(f"  ✗ FALSE POSITIVE RATE: FAIL ({fp_rate:.2%} >= 2%)")
    
    # check 3: drawdown acceptable
    total_checks += 1
    dd = metrics.get('max_drawdown', 0)
    if dd < 0.08:
        lines.append(f"  ✓ MAX DRAWDOWN: PASS ({dd:.2%} < 8%)")
        passed_checks += 1
    else:
        lines.append(f"  ✗ MAX DRAWDOWN: FAIL ({dd:.2%} >= 8%)")
    
    # check 4: reconciliation clean
    total_checks += 1
    if unresolved == 0:
        lines.append("  ✓ RECONCILIATION: PASS (all orders resolved)")
        passed_checks += 1
    else:
        lines.append(f"  ✗ RECONCILIATION: FAIL ({unresolved} unresolved)")
    
    lines.append("")
    lines.append(f"OVERALL: {passed_checks}/{total_checks} checks passed")
    if passed_checks == total_checks:
        lines.append("RESULT: ✓ BACKTEST PASSED")
    else:
        lines.append(f"RESULT: ✗ BACKTEST FAILED ({total_checks - passed_checks} issues)")
    lines.append("")
    lines.append("=" * 80)
    
    return "\n".join(lines)


def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python tools/generate_summary.py <run_dir>")
        sys.exit(2)
    summary = generate_summary(sys.argv[1])
    print(summary)
    # also write to file
    out_file = Path(sys.argv[1]) / "SUMMARY.txt"
    out_file.write_text(summary, encoding="utf-8")
    print(f"\nSummary written to {out_file}")


if __name__ == '__main__':
    main()
