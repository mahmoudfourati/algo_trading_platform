"""HTML report generation for Phase 5 backtesting runs."""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .metrics import BacktestMetrics

if TYPE_CHECKING:
  from .engine import BacktestConfig
from typing import TYPE_CHECKING, Optional
from .scenario_comparison import ScenarioComparison


class BacktestReportGenerator:
    """Render a self-contained HTML report for a single backtest run."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def write_report(self, *, config: BacktestConfig, metrics: BacktestMetrics) -> Path:
        report_path = self.output_dir / "report.html"
        report_path.write_text(self.render(config=config, metrics=metrics), encoding="utf-8")
        return report_path

    def render(self, *, config: BacktestConfig, metrics: BacktestMetrics, comparisons: Optional[list[ScenarioComparison]] = None) -> str:
        assumptions = [
            "Historical ticks are replayed through the live Layer 1 and Layer 2 code paths.",
            "Multi-source generation in backtesting is synthetic and slightly optimistic for T2.",
            "Transaction costs assume a 0.1% Binance fee per trade.",
        ]
        config_snapshot = self._config_snapshot(config)
        events_html = self._render_events(metrics)
        comparison_html = self._render_comparisons(comparisons) if comparisons else ""

        return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Phase 5 Backtest Report</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #f5f7fb; color: #1f2937; }}
    .card {{ background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 18px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08); }}
    h1, h2 {{ margin: 0 0 12px 0; }}
    h1 {{ font-size: 28px; }}
    h2 {{ font-size: 18px; border-bottom: 1px solid #e5e7eb; padding-bottom: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }}
    th {{ width: 34%; color: #374151; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .metric {{ background: #eef2ff; border-left: 4px solid #4f46e5; padding: 12px; border-radius: 10px; }}
    .muted {{ color: #6b7280; }}
    code, pre {{ background: #0f172a; color: #e2e8f0; border-radius: 8px; }}
    pre {{ padding: 14px; overflow-x: auto; }}
    ul {{ margin: 8px 0 0 20px; }}
      .better {{ color: #059669; font-weight: 500; }}
      .worse {{ color: #dc2626; font-weight: 500; }}
      .neutral {{ color: #6b7280; }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>Phase 5 Backtest Report</h1>
    <div class=\"muted\">Generated {datetime.now(timezone.utc).isoformat()} UTC</div>
  </div>

  <div class=\"card grid\">
    <div class=\"metric\"><strong>Run ID</strong><br>{html.escape(metrics.run_id)}</div>
    <div class=\"metric\"><strong>Symbol</strong><br>{html.escape(metrics.symbol)}</div>
    <div class=\"metric\"><strong>Scenario</strong><br>{html.escape(metrics.scenario)}</div>
    <div class=\"metric\"><strong>Ticks</strong><br>{metrics.total_ticks}</div>
    <div class=\"metric\"><strong>Sharpe</strong><br>{metrics.sharpe_ratio:.4f}</div>
    <div class=\"metric\"><strong>Max Drawdown</strong><br>{metrics.max_drawdown:.4f}</div>
    <div class=\"metric\"><strong>Detection Rate</strong><br>{metrics.get_detection_rate():.2%}</div>
    <div class=\"metric\"><strong>False Positive Rate</strong><br>{metrics.get_false_positive_rate():.2%}</div>
  </div>

  <div class=\"card\">
    <h2>Results Summary</h2>
    <table>
      <tr><th>Gross P&L</th><td>{metrics.gross_pnl:.6f}</td></tr>
      <tr><th>Net P&L</th><td>{metrics.net_pnl:.6f}</td></tr>
      <tr><th>Win Rate</th><td>{metrics.win_rate:.2%}</td></tr>
      <tr><th>Latency Proxy</th><td>{metrics.end_to_end_latency_ms:.3f} ms</td></tr>
      <tr><th>NORMAL State %</th><td>{metrics.normal_state_pct:.2%}</td></tr>
      <tr><th>Permutation p-value</th><td>{metrics.permutation_p_value:.6f}</td></tr>
      <tr><th>Attack Episodes</th><td>{metrics.attack_episode_count}</td></tr>
      <tr><th>Attack Episodes Detected</th><td>{metrics.attack_episode_detected_count}</td></tr>
      <tr><th>Attack Episodes Undetected</th><td>{max(0, metrics.attack_episode_count - metrics.attack_episode_detected_count)}</td></tr>
      <tr><th>First Detection Latency (ms)</th><td>{metrics.attack_detection_latency_ms_first:.3f}</td></tr>
      <tr><th>Mean Detection Latency (ms)</th><td>{metrics.attack_detection_latency_ms_mean:.3f}</td></tr>
      <tr><th>Max Detection Latency (ms)</th><td>{metrics.attack_detection_latency_ms_max:.3f}</td></tr>
      <tr><th>Injected Anomalies</th><td>{metrics.injected_anomalies}</td></tr>
      <tr><th>Detected Anomalies</th><td>{metrics.detected_anomalies}</td></tr>
      <tr><th>False Positives</th><td>{metrics.false_positives}</td></tr>
    </table>
  </div>

  <div class=\"card\">
    <h2>Assumptions</h2>
    <ul>
      {''.join(f'<li>{html.escape(item)}</li>' for item in assumptions)}
    </ul>
  </div>

  <div class=\"card\">
    <h2>Config Snapshot</h2>
    <pre>{html.escape(json.dumps(config_snapshot, indent=2, sort_keys=True))}</pre>
  </div>

  <div class=\"card\">
    <h2>Scoring Events</h2>
    {events_html}
      {comparison_html}
  </div>
</body>
</html>
"""

    def _config_snapshot(self, config: BacktestConfig) -> dict[str, object]:
        snapshot = asdict(config)
        for key, value in list(snapshot.items()):
            if isinstance(value, Path):
                snapshot[key] = str(value)
            elif isinstance(value, tuple):
                snapshot[key] = list(value)
            elif isinstance(value, datetime):
                snapshot[key] = value.astimezone(timezone.utc).isoformat()
        return snapshot

    def _render_events(self, metrics: BacktestMetrics) -> str:
        if not metrics.events:
            return '<div class="muted">No scoring events were captured for this run.</div>'

        rows = []
        for event in metrics.events[-25:]:
            rows.append(
                "<tr>"
                f"<td>{html.escape(event.timestamp.isoformat())}</td>"
                f"<td>{html.escape(event.decision_state)}</td>"
                f"<td>{event.anomaly_score:.4f}</td>"
                f"<td>{event.trust_score:.4f}</td>"
                f"<td>{event.if_score:.4f}</td>"
                f"<td>{event.hst_score:.4f}</td>"
                f"<td>{'yes' if event.mad_triggered else 'no'}</td>"
                "</tr>"
            )

        return (
            "<table>"
            "<tr><th>Timestamp</th><th>State</th><th>Anomaly</th><th>Trust</th><th>IF</th><th>HST</th><th>MAD</th></tr>"
            f"{''.join(rows)}"
            "</table>"
        )

    def _render_comparisons(self, comparisons: Optional[list[ScenarioComparison]]) -> str:
        if not comparisons:
            return ""

        sections = []
        for comparison in comparisons:
            rows = []
            for delta in comparison.deltas:
                direction_class = delta.direction
                percent_fmt = f"{delta.percent_change:+.2f}%"
                rows.append(
                    "<tr>"
                    f"<td>{html.escape(delta.metric_name)}</td>"
                    f"<td>{delta.baseline_value:.6g}</td>"
                    f"<td>{delta.attack_value:.6g}</td>"
                    f"<td>{delta.delta:+.6g}</td>"
                    f'<td class="{direction_class}">{percent_fmt}</td>'
                    f"<td>{html.escape(delta.direction)}</td>"
                    "</tr>"
                )

            section_html = (
                f'<div class="card">'
                f'<h2>Scenario: {html.escape(comparison.scenario_name.title())}</h2>'
                f"<table>"
                f"<tr><th>Metric</th><th>Baseline</th><th>Attack</th><th>Delta</th><th>Change %</th><th>Direction</th></tr>"
                f"{''.join(rows)}"
                f"</table>"
                f"</div>"
            )
            sections.append(section_html)

        return (
            '<div class="card"><h2>Scenario Comparison Dashboard</h2></div>'
            + "".join(sections)
        )