"""Metrics models for Phase 5 backtesting results and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import statistics
from typing import List


@dataclass
class ScoringEvent:
    """Per-tick scoring snapshot captured during replay."""

    timestamp: datetime
    symbol: str
    anomaly_score: float
    regime: int
    if_score: float
    hst_score: float
    mad_triggered: bool
    decision_state: str
    trust_score: float


@dataclass
class BacktestMetrics:
    """Aggregate metrics produced by a backtest run."""

    run_id: str
    start_time: datetime
    end_time: datetime
    symbol: str
    scenario: str
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    end_to_end_latency_ms: float = 0.0
    normal_state_pct: float = 0.0
    permutation_p_value: float = 1.0
    equity_curve_path: str = ""
    injected_anomalies: int = 0
    detected_anomalies: int = 0
    false_positives: int = 0
    attack_episode_count: int = 0
    attack_episode_detected_count: int = 0
    attack_detection_latency_ms_first: float = 0.0
    attack_detection_latency_ms_mean: float = 0.0
    attack_detection_latency_ms_max: float = 0.0
    risk_approved_orders: int = 0
    risk_rejected_orders: int = 0
    risk_reduced_ticks: int = 0
    risk_halted_ticks: int = 0
    total_ticks: int = 0
    layer3_statistics: dict[str, object] = field(default_factory=dict)
    layer4_statistics: dict[str, object] = field(default_factory=dict)
    layer5_statistics: dict[str, object] = field(default_factory=dict)
    events: List[ScoringEvent] = field(default_factory=list)

    def _trust_values(self) -> list[float]:
        return [event.trust_score for event in self.events]

    def _t2_values(self) -> list[float]:
        return [max(0.0, min(1.0, 1.0 - event.anomaly_score)) for event in self.events]

    def _t3_values(self) -> list[float]:
        return [event.if_score for event in self.events]

    @staticmethod
    def _percentile(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        if len(ordered) == 1:
            return float(ordered[0])
        position = p * (len(ordered) - 1)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        if lower == upper:
            return float(ordered[lower])
        fraction = position - lower
        return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)

    def get_layer1_trust_statistics(self) -> dict[str, float]:
        trust = self._trust_values()
        if not trust:
            return {}
        return {
            "mean": statistics.mean(trust),
            "std": statistics.stdev(trust) if len(trust) > 1 else 0.0,
            "min": min(trust),
            "max": max(trust),
            "p5": self._percentile(trust, 0.05),
            "p25": self._percentile(trust, 0.25),
            "p50": self._percentile(trust, 0.50),
            "p75": self._percentile(trust, 0.75),
            "p95": self._percentile(trust, 0.95),
            "range": max(trust) - min(trust),
        }

    def get_layer1_soak_checklist(self) -> dict[str, object]:
        trust_stats = self.get_layer1_trust_statistics()
        if not trust_stats:
            return {}

        t2 = self._t2_values()
        t3 = self._t3_values()
        return {
            "trust_score_std_gt_zero": trust_stats["std"] > 0.0,
            "trust_score_range_gt_001": trust_stats["range"] > 0.01,
            "trust_score_p95_minus_p5_gt_001": (trust_stats["p95"] - trust_stats["p5"]) > 0.01,
            "t2_range_gt_001": (max(t2) - min(t2)) > 0.01 if t2 else False,
            "t3_range_gt_001": (max(t3) - min(t3)) > 0.01 if t3 else False,
            "normal_state_pct": self.normal_state_pct,
        }

    def get_detection_rate(self) -> float:
        """Return detected anomalies divided by injected anomalies."""
        return self.detected_anomalies / self.injected_anomalies if self.injected_anomalies > 0 else 0.0

    def get_false_positive_rate(self) -> float:
        """Return false positives divided by normal ticks."""
        total_normal = self.total_ticks - self.injected_anomalies
        return self.false_positives / total_normal if total_normal > 0 else 0.0

    def get_attack_detection_timing_summary(self) -> dict[str, float | int]:
        """Return a compact summary of attack detection timing."""

        undetected = max(0, self.attack_episode_count - self.attack_episode_detected_count)
        return {
            "attack_episode_count": self.attack_episode_count,
            "attack_episode_detected_count": self.attack_episode_detected_count,
            "attack_episode_undetected_count": undetected,
            "attack_detection_latency_ms_first": self.attack_detection_latency_ms_first,
            "attack_detection_latency_ms_mean": self.attack_detection_latency_ms_mean,
            "attack_detection_latency_ms_max": self.attack_detection_latency_ms_max,
        }

    def to_dict(self) -> dict[str, object]:
        """Serialize the result bundle for JSON output."""

        layer1_trust = self.get_layer1_trust_statistics()
        layer1_soak_checklist = self.get_layer1_soak_checklist()

        return {
            "run_id": self.run_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "symbol": self.symbol,
            "scenario": self.scenario,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "end_to_end_latency_ms": self.end_to_end_latency_ms,
            "normal_state_pct": self.normal_state_pct,
            "permutation_p_value": self.permutation_p_value,
            "equity_curve_path": self.equity_curve_path,
            "injected_anomalies": self.injected_anomalies,
            "detected_anomalies": self.detected_anomalies,
            "false_positives": self.false_positives,
            "attack_episode_count": self.attack_episode_count,
            "attack_episode_detected_count": self.attack_episode_detected_count,
            "attack_episode_undetected_count": max(0, self.attack_episode_count - self.attack_episode_detected_count),
            "attack_detection_latency_ms_first": self.attack_detection_latency_ms_first,
            "attack_detection_latency_ms_mean": self.attack_detection_latency_ms_mean,
            "attack_detection_latency_ms_max": self.attack_detection_latency_ms_max,
            "risk_approved_orders": self.risk_approved_orders,
            "risk_rejected_orders": self.risk_rejected_orders,
            "risk_reduced_ticks": self.risk_reduced_ticks,
            "risk_halted_ticks": self.risk_halted_ticks,
            "total_ticks": self.total_ticks,
            "layer3_statistics": self.layer3_statistics,
            "layer4_statistics": self.layer4_statistics,
            "layer5_statistics": self.layer5_statistics,
            "detection_rate": self.get_detection_rate(),
            "false_positive_rate": self.get_false_positive_rate(),
            "layer1_trust_statistics": layer1_trust,
            "layer1_soak_checklist": layer1_soak_checklist,
        }
