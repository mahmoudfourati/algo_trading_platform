import time
import sqlite3
from pathlib import Path
from typing import Dict

import pytest

from services.layer5_execution.engine import ExecutionEngine
from services.layer5_execution.adapters import DuplicateOrderError, OrderStatusResult, SimulatedExecutionAdapter
from services.layer5_execution.persistence import OrderStore, PersistedOrder


class FlakyAdapter(SimulatedExecutionAdapter):
    """Adapter that fails a number of times for a given client_order_id before succeeding."""

    def __init__(self, *, fail_times: int = 3, **kwargs):
        super().__init__(**kwargs)
        self.fail_times = fail_times
        self._counts: Dict[str, int] = {}

    def execute(self, order: Dict, reference_price: float):
        coid = order.get("client_order_id")
        if coid is None:
            # behave normally
            return super().execute(order, reference_price)

        cnt = self._counts.get(coid, 0)
        if cnt < self.fail_times:
            self._counts[coid] = cnt + 1
            raise RuntimeError("transient network error")
        return super().execute(order, reference_price)


def test_retry_then_confirm(tmp_path: Path) -> None:
    db = tmp_path / "orders.sqlite"
    adapter = FlakyAdapter(fail_times=2)
    engine = ExecutionEngine(adapter=adapter, portfolio_value=1.0, persistence_db=db)

    approved = {"symbol": "BTCUSDT", "direction": "LONG", "size_pct": 0.1}
    executed = engine.submit_order(approved, reference_price=100.0)
    assert executed.filled_pct > 0

    # confirm DB has no pending entries
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM orders WHERE status = 'PENDING'")
    pending = cur.fetchone()[0]
    cur.close()
    conn.close()
    assert pending == 0


def test_fail_and_dead_letter(tmp_path: Path) -> None:
    db = tmp_path / "orders2.sqlite"
    adapter = FlakyAdapter(fail_times=10)
    engine = ExecutionEngine(adapter=adapter, portfolio_value=1.0, persistence_db=db)

    approved = {"symbol": "BTCUSDT", "direction": "LONG", "size_pct": 0.1}
    with pytest.raises(RuntimeError):
        engine.submit_order(approved, reference_price=100.0)

    # check dead_letter contains the client_order_id
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM dead_letter")
    dlq = cur.fetchone()[0]
    cur.close()
    conn.close()
    assert dlq == 1


def test_duplicate_order_is_treated_as_success(tmp_path: Path) -> None:
    db = tmp_path / "orders_dup.sqlite"
    adapter = SimulatedExecutionAdapter()
    engine = ExecutionEngine(adapter=adapter, portfolio_value=1.0, persistence_db=db)

    engine._make_client_order_id = lambda **kwargs: "fixed-client-order-id"  # type: ignore[method-assign]

    approved = {"symbol": "BTCUSDT", "direction": "LONG", "size_pct": 0.1}
    first = engine.submit_order(approved, reference_price=100.0)
    second = engine.submit_order(approved, reference_price=100.0)

    assert first.order_id == second.order_id == "fixed-client-order-id"
    assert second.note == "full"


def test_startup_reconciles_pending_order_after_crash(tmp_path: Path) -> None:
    db = tmp_path / "orders_reconcile.sqlite"
    adapter = SimulatedExecutionAdapter()

    client_order_id = "pending-client-order-id"
    adapter._status[client_order_id] = OrderStatusResult(
        client_order_id=client_order_id,
        status="FILLED",
        filled_pct=0.15,
        avg_fill_price=101.0,
        fee_paid=1.5,
        latency_ms=22.0,
        note="recovered",
    )

    store = OrderStore(db)
    store.insert_order(
        PersistedOrder(
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            direction="LONG",
            size_pct=0.15,
            timestamp_utc=1_700_000_000_000,
            session_id="session-crash",
            status="PENDING",
            metadata={"symbol": "BTCUSDT", "direction": "LONG", "size_pct": 0.15, "timestamp_utc": 1_700_000_000_000, "session_id": "session-crash"},
        )
    )
    store.close()

    engine = ExecutionEngine(adapter=adapter, portfolio_value=1.0, persistence_db=db)
    pending = engine.store.fetch_pending() if engine.store is not None else []
    assert pending == []
    execution = engine.get_execution(client_order_id)
    assert execution is not None
    assert execution.note == "recovered"


def test_simulated_adapter_latency_fee_and_partial_fill_controls() -> None:
    adapter = SimulatedExecutionAdapter(
        slippage_pct=0.001,
        fee_pct=0.001,
        partial_fill_threshold=0.2,
        partial_fill_ratio=0.25,
        latency_ms_base=10.0,
        latency_ms_per_size_pct=40.0,
        latency_ms_jitter=0.0,
        fee_schedule={"binance": 0.0005},
    )
    engine = ExecutionEngine(adapter=adapter, portfolio_value=1000.0)
    engine._make_client_order_id = lambda **kwargs: "latency-fee-case"  # type: ignore[method-assign]

    fake_order = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "size_pct": 0.5,
        "entry_price": 100.0,
        "exchange_id": "binance",
    }

    executed = engine.submit_order(fake_order, reference_price=100.0)

    assert executed.filled_pct == pytest.approx(0.2 + (0.5 - 0.2) * 0.25)
    assert executed.avg_fill_price == pytest.approx(100.0 * 1.001)
    assert executed.fee_paid > 0.0
    assert adapter.get_order_status("latency-fee-case") is not None
