"""SQLite persistence for Phase 5 backtest runs."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .metrics import BacktestMetrics, ScoringEvent


class ResultsDB:
    """Store run-level metrics and scoring events in SQLite."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    metrics_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scoring_events (
                    run_id TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    anomaly_score REAL NOT NULL,
                    regime INTEGER NOT NULL,
                    if_score REAL NOT NULL,
                    hst_score REAL NOT NULL,
                    mad_triggered INTEGER NOT NULL,
                    decision_state TEXT NOT NULL,
                    trust_score REAL NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES backtest_runs(run_id)
                )
                """
            )

    def save_run(self, metrics: BacktestMetrics) -> None:
        events = metrics.events
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO backtest_runs
                (run_id, created_at, symbol, scenario, start_time, end_time, metrics_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metrics.run_id,
                    datetime.utcnow().isoformat(),
                    metrics.symbol,
                    metrics.scenario,
                    metrics.start_time.isoformat(),
                    metrics.end_time.isoformat(),
                    json.dumps(metrics.to_dict(), sort_keys=True),
                ),
            )
            conn.execute("DELETE FROM scoring_events WHERE run_id = ?", (metrics.run_id,))
            conn.executemany(
                """
                INSERT INTO scoring_events
                (run_id, event_time, symbol, anomaly_score, regime, if_score, hst_score, mad_triggered, decision_state, trust_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        metrics.run_id,
                        event.timestamp.isoformat(),
                        event.symbol,
                        event.anomaly_score,
                        event.regime,
                        event.if_score,
                        event.hst_score,
                        1 if event.mad_triggered else 0,
                        event.decision_state,
                        event.trust_score,
                    )
                    for event in events
                ],
            )

    def list_run_ids(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT run_id FROM backtest_runs ORDER BY created_at DESC").fetchall()
        return [str(row[0]) for row in rows]