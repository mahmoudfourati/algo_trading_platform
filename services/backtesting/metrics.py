"""Metrics models for Phase 5 backtesting results and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
    events: List[ScoringEvent] = field(default_factory=list)

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
            "detection_rate": self.get_detection_rate(),
            "false_positive_rate": self.get_false_positive_rate(),
        }
