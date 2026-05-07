"""SQLite WAL-based persistence for execution orders.

Provides a small deterministic idempotency store: insert before send,
mark confirmed/failed, and a dead-letter queue table. Uses WAL mode and
simple retry-safe semantics suitable for testing and backtests.
"""

from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PersistedOrder:
    client_order_id: str
    symbol: str
    direction: str
    size_pct: float
    timestamp_utc: int
    session_id: str
    status: str
    metadata: Dict[str, Any]


class OrderStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=10, isolation_level=None)
        # use WAL for durability and concurrency
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                size_pct REAL NOT NULL,
                timestamp_utc INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dead_letter (
                client_order_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                failed_at INTEGER NOT NULL
            )
            """
        )
        cur.close()

    def insert_order(self, po: PersistedOrder) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO orders (client_order_id, symbol, direction, size_pct, timestamp_utc, session_id, status, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                po.client_order_id,
                po.symbol,
                po.direction,
                float(po.size_pct),
                int(po.timestamp_utc),
                po.session_id,
                po.status,
                json.dumps(po.metadata or {}),
            ),
        )
        cur.close()

    def get_order(self, client_order_id: str) -> Optional[PersistedOrder]:
        cur = self._conn.cursor()
        cur.execute("SELECT client_order_id, symbol, direction, size_pct, timestamp_utc, session_id, status, metadata FROM orders WHERE client_order_id = ?", (client_order_id,))
        row = cur.fetchone()
        cur.close()
        if row is None:
            return None
        return PersistedOrder(
            client_order_id=row[0],
            symbol=row[1],
            direction=row[2],
            size_pct=float(row[3]),
            timestamp_utc=int(row[4]),
            session_id=row[5],
            status=row[6],
            metadata=json.loads(row[7]) if row[7] else {},
        )

    def mark_confirmed(self, client_order_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute("UPDATE orders SET status = ? WHERE client_order_id = ?", ("CONFIRMED", client_order_id))
        cur.close()

    def mark_duplicate(self, client_order_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute("UPDATE orders SET status = ? WHERE client_order_id = ?", ("DUPLICATE", client_order_id))
        cur.close()

    def mark_failed(self, client_order_id: str) -> None:
        cur = self._conn.cursor()
        # move to dead_letter
        cur.execute("SELECT metadata FROM orders WHERE client_order_id = ?", (client_order_id,))
        row = cur.fetchone()
        payload = row[0] if row is not None else "{}"
        cur.execute("INSERT OR REPLACE INTO dead_letter (client_order_id, payload, failed_at) VALUES (?, ?, strftime('%s','now'))", (client_order_id, payload))
        cur.execute("DELETE FROM orders WHERE client_order_id = ?", (client_order_id,))
        cur.close()

    def list_dead_letter(self) -> List[PersistedOrder]:
        cur = self._conn.cursor()
        cur.execute("SELECT client_order_id, payload, failed_at FROM dead_letter ORDER BY failed_at ASC")
        rows = cur.fetchall()
        cur.close()
        out: List[PersistedOrder] = []
        for client_order_id, payload, failed_at in rows:
            meta = json.loads(payload) if payload else {}
            out.append(
                PersistedOrder(
                    client_order_id=client_order_id,
                    symbol=str(meta.get("symbol", "")),
                    direction=str(meta.get("direction", "")),
                    size_pct=float(meta.get("size_pct", 0.0)),
                    timestamp_utc=int(meta.get("timestamp_utc", failed_at)),
                    session_id=str(meta.get("session_id", "")),
                    status="DEAD_LETTER",
                    metadata=meta,
                )
            )
        return out

    def fetch_pending(self) -> List[PersistedOrder]:
        cur = self._conn.cursor()
        cur.execute("SELECT client_order_id, symbol, direction, size_pct, timestamp_utc, session_id, status, metadata FROM orders WHERE status = ?", ("PENDING",))
        rows = cur.fetchall()
        cur.close()
        out: List[PersistedOrder] = []
        for r in rows:
            meta = json.loads(r[7]) if r[7] else {}
            out.append(
                PersistedOrder(
                    client_order_id=r[0],
                    symbol=r[1],
                    direction=r[2],
                    size_pct=float(r[3]),
                    timestamp_utc=int(r[4]),
                    session_id=r[5],
                    status=r[6],
                    metadata=meta,
                )
            )
        return out

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
