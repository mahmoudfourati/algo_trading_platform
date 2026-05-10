"""HTML report generation for Phase 5 backtesting runs."""

from __future__ import annotations

import html
import json
import statistics
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
        layer_stats_html = self._render_layer_statistics(metrics)
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
    <h2>Layer Statistics</h2>
    {layer_stats_html}
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

    def _render_layer_statistics(self, metrics: BacktestMetrics) -> str:
        """Render comprehensive layer-by-layer statistics."""
        if not metrics.events:
            return '<div class="muted">No events for layer statistics.</div>'
        
        stats = self._compute_layer_statistics(metrics.events)
        
        # Merge metrics-based stats
        if 'layer45_stats' in stats:
            stats['layer45_stats'].update({
                'approved_orders': metrics.risk_approved_orders,
                'rejected_orders': metrics.risk_rejected_orders,
                'reduced_ticks': metrics.risk_reduced_ticks,
                'halted_ticks': metrics.risk_halted_ticks,
            })
        
        html_parts = []
        
        # Layer 1: Trust Score Statistics
        if 'layer1_stats' in stats:
            l1 = stats['layer1_stats']
            html_parts.append("<h3>Layer 1: Consensus & Trust</h3>")
            html_parts.append("<table>")
            html_parts.append(f"<tr><th>Trust Score Mean</th><td>{l1.get('trust_mean', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>Trust Score Std Dev</th><td>{l1.get('trust_std', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>Trust Score Min</th><td>{l1.get('trust_min', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>Trust Score Max</th><td>{l1.get('trust_max', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>Trust Score P25</th><td>{l1.get('trust_p25', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>Trust Score P50</th><td>{l1.get('trust_p50', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>Trust Score P75</th><td>{l1.get('trust_p75', 0):.6f}</td></tr>")
            html_parts.append("</table>")
        
        # Layer 2: Anomaly Detection Statistics
        if 'layer2_stats' in stats:
            l2 = stats['layer2_stats']
            html_parts.append("<h3>Layer 2: Anomaly Detection</h3>")
            html_parts.append("<table>")
            html_parts.append(f"<tr><th>Anomaly Score Mean</th><td>{l2.get('anom_mean', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>Anomaly Score Std Dev</th><td>{l2.get('anom_std', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>Anomaly Score Min</th><td>{l2.get('anom_min', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>Anomaly Score Max</th><td>{l2.get('anom_max', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>IF Score Mean</th><td>{l2.get('if_mean', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>HST Score Mean</th><td>{l2.get('hst_mean', 0):.6f}</td></tr>")
            html_parts.append(f"<tr><th>NORMAL State Events</th><td>{l2.get('state_normal', 0)}</td></tr>")
            html_parts.append(f"<tr><th>CONSERVATIVE State Events</th><td>{l2.get('state_conservative', 0)}</td></tr>")
            html_parts.append(f"<tr><th>DEGRADED State Events</th><td>{l2.get('state_degraded', 0)}</td></tr>")
            html_parts.append(f"<tr><th>HALT State Events</th><td>{l2.get('state_halt', 0)}</td></tr>")
            html_parts.append(f"<tr><th>MAD Triggered Count</th><td>{l2.get('mad_triggered', 0)}</td></tr>")
            html_parts.append("</table>")
        
        if metrics.layer3_statistics:
            html_parts.append(self._render_flat_dict_section("Layer 3: Strategy Signals", metrics.layer3_statistics))

        if metrics.layer4_statistics:
            html_parts.append(self._render_flat_dict_section("Layer 4: Risk Management", metrics.layer4_statistics))

        if metrics.layer5_statistics:
            html_parts.append(self._render_flat_dict_section("Layer 5: Execution", metrics.layer5_statistics))

        return "".join(html_parts) if html_parts else '<div class="muted">No layer statistics available.</div>'

    def _compute_layer_statistics(self, events: list) -> dict:
        """Compute comprehensive statistics from ScoringEvents."""
        if not events:
            return {}
        
        stats = {}
        
        # Layer 1: Trust Score Statistics
        trust_scores = [e.trust_score for e in events if hasattr(e, 'trust_score')]
        if trust_scores:
            stats['layer1_stats'] = {
                'trust_mean': sum(trust_scores) / len(trust_scores),
                'trust_std': statistics.stdev(trust_scores) if len(trust_scores) > 1 else 0.0,
                'trust_min': min(trust_scores),
                'trust_max': max(trust_scores),
                'trust_p25': self._percentile(trust_scores, 0.25),
                'trust_p50': self._percentile(trust_scores, 0.50),
                'trust_p75': self._percentile(trust_scores, 0.75),
            }
        
        # Layer 2: Anomaly Detection Statistics
        anom_scores = [e.anomaly_score for e in events if hasattr(e, 'anomaly_score')]
        if_scores = [e.if_score for e in events if hasattr(e, 'if_score')]
        hst_scores = [e.hst_score for e in events if hasattr(e, 'hst_score')]
        
        state_counts = {}
        for e in events:
            if hasattr(e, 'decision_state'):
                state_counts[e.decision_state] = state_counts.get(e.decision_state, 0) + 1
        
        mad_count = sum(1 for e in events if hasattr(e, 'mad_triggered') and e.mad_triggered)
        
        if anom_scores:
            stats['layer2_stats'] = {
                'anom_mean': sum(anom_scores) / len(anom_scores),
                'anom_std': statistics.stdev(anom_scores) if len(anom_scores) > 1 else 0.0,
                'anom_min': min(anom_scores),
                'anom_max': max(anom_scores),
                'if_mean': sum(if_scores) / len(if_scores) if if_scores else 0.0,
                'hst_mean': sum(hst_scores) / len(hst_scores) if hst_scores else 0.0,
                'state_normal': state_counts.get('NORMAL', 0),
                'state_conservative': state_counts.get('CONSERVATIVE', 0),
                'state_degraded': state_counts.get('DEGRADED', 0),
                'state_halt': state_counts.get('HALT', 0),
                'mad_triggered': mad_count,
            }
        
        return stats

    def _percentile(self, data: list[float], p: float) -> float:
        """Compute percentile of a list of floats."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = p * (len(sorted_data) - 1)
        lower = int(index)
        upper = lower + 1
        if upper >= len(sorted_data):
            return float(sorted_data[-1])
        return sorted_data[lower] + (index - lower) * (sorted_data[upper] - sorted_data[lower])


    def _render_flat_dict_section(self, title: str, values: dict[str, object]) -> str:
        rows = []
        for key in sorted(values.keys()):
            value = values[key]
            if isinstance(value, float):
                display = f"{value:.6f}"
            else:
                display = html.escape(str(value))
            rows.append(f"<tr><th>{html.escape(key.replace('_', ' ').title())}</th><td>{display}</td></tr>")
        return f"<h3>{html.escape(title)}</h3><table>{''.join(rows)}</table>"

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