"""Layer 5 execution engine for pre- and post-execution handling.

The engine accepts an ApprovedOrder-like mapping (or object) and routes it
to an adapter (simulated or real) which returns fill details. The engine
tracks order records and exposes lightweight query methods used by the
backtester and unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional
import time
import uuid
import hashlib
import random
from pathlib import Path

from services.layer5_execution.adapters import DuplicateOrderError, SimulatedExecutionAdapter, SimulatedFillResult, OrderStatusResult
from services.layer5_execution.persistence import OrderStore, PersistedOrder


@dataclass
class OrderRecord:
    order_id: str
    symbol: str
    direction: str
    requested_size_pct: float
    approved_size_pct: float
    entry_price: float
    stop_loss_price: Optional[float]
    take_profit_price: Optional[float]
    created_at_utc: int
    portfolio_value: float = 1.0
    metadata: Dict = field(default_factory=dict)


@dataclass
class ExecutedOrder:
    order_id: str
    filled_pct: float
    avg_fill_price: float
    fee_paid: float
    slippage_pct: float
    note: Optional[str]


@dataclass
class ExecutionTelemetry:
    """Counters describing Layer 5 execution behavior."""

    submitted_orders: int = 0
    executed_orders: int = 0
    duplicate_orders: int = 0
    retry_attempts: int = 0
    failed_submissions: int = 0
    close_all_orders: int = 0


class ExecutionEngine:
    """Execution engine wrapping an adapter and tracking in-flight / executed orders.

    The engine accepts a mapping representing an `ApprovedOrder` or the
    approved-order dataclass itself. To keep integration simple, the engine
    tolerates mappings and extracts commonly used fields.
    """

    def __init__(self, *, adapter: Optional[SimulatedExecutionAdapter] = None, portfolio_value: float = 1.0, persistence_db: Optional[Path] = None) -> None:
        self.adapter = adapter or SimulatedExecutionAdapter()
        self.portfolio_value = float(portfolio_value)
        self._orders: Dict[str, OrderRecord] = {}
        self._executions: Dict[str, ExecutedOrder] = {}
        self._next_id = 1
        self.session_id = uuid.uuid4().hex
        self._rand = random.Random(42)
        self.telemetry = ExecutionTelemetry()

        # persistence
        self.store: Optional[OrderStore] = OrderStore(persistence_db) if persistence_db is not None else None
        # perform startup reconciliation if store present
        if self.store is not None:
            self.reconcile_pending_orders()

    def _make_order_id(self) -> str:
        oid = f"exec-{int(time.time() * 1000)}-{self._next_id}"
        self._next_id += 1
        return oid

    def _make_client_order_id(self, *, symbol: str, direction: str, size_pct: float, timestamp_ms: int) -> str:
        key = f"{symbol}|{direction}|{float(size_pct):.8f}|{int(timestamp_ms)}|{self.session_id}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _backoff_and_jitter(self, attempt: int) -> float:
        # blueprint schedule: 0.5+U(0,0.5), 1+U(0,1), 2+U(0,2)
        if attempt == 0:
            base = 0.5
            jitter = self._rand.uniform(0, 0.5)
        elif attempt == 1:
            base = 1.0
            jitter = self._rand.uniform(0, 1.0)
        else:
            base = 2.0
            jitter = self._rand.uniform(0, 2.0)
        return base + jitter

    def _send_to_adapter_and_record(self, approved_order: Mapping, *, reference_price: Optional[float] = None) -> ExecutedOrder:
        # direct adapter call and local in-memory recording used both at submit and reconciliation
        
        # Convert to dict if needed (handles both Pydantic models and plain mappings)
        if isinstance(approved_order, Mapping):
            order_dict = dict(approved_order)
        else:
            # For Pydantic models, use model_dump(); for other objects, extract known fields
            if hasattr(approved_order, 'model_dump'):
                order_dict = approved_order.model_dump()
            else:
                # Fallback: manually build dict from known fields
                order_dict = {
                    "symbol": getattr(approved_order, "symbol", ""),
                    "direction": getattr(approved_order, "direction", "LONG"),
                    "size_pct": getattr(approved_order, "size_pct", 0.0),
                    "entry_price": getattr(approved_order, "entry_price", None),
                    "stop_loss_price": getattr(approved_order, "stop_loss_price", None),
                    "take_profit_price": getattr(approved_order, "take_profit_price", None),
                }
        
        fill = self.adapter.execute({**order_dict, "portfolio_value": self.portfolio_value}, reference_price=float(reference_price) if reference_price is not None else None)

        # if the approved_order contained a client_order_id, use it to update store
        coid = approved_order.get("client_order_id") if isinstance(approved_order, Mapping) else getattr(approved_order, "client_order_id", None)
        if coid and self.store is not None:
            try:
                self.store.mark_confirmed(coid)
            except Exception:
                pass

        order_id = (approved_order.get("client_order_id") if isinstance(approved_order, Mapping) else getattr(approved_order, "client_order_id", None)) or self._make_order_id()
        executed = ExecutedOrder(order_id=order_id, filled_pct=fill.filled_pct, avg_fill_price=fill.avg_fill_price, fee_paid=fill.fee_paid, slippage_pct=fill.slippage_pct, note=fill.note)
        self._executions[order_id] = executed
        self.telemetry.executed_orders += 1
        return executed

    def _status_result_to_execution(self, status: OrderStatusResult) -> ExecutedOrder:
        executed = ExecutedOrder(
            order_id=status.client_order_id,
            filled_pct=status.filled_pct,
            avg_fill_price=status.avg_fill_price,
            fee_paid=status.fee_paid,
            slippage_pct=0.0,
            note=status.note or status.status.lower(),
        )
        self._executions[status.client_order_id] = executed
        self.telemetry.executed_orders += 1
        return executed

    def _query_adapter_status(self, client_order_id: str) -> Optional[OrderStatusResult]:
        query_fn = getattr(self.adapter, "get_order_status", None)
        if query_fn is None:
            return None
        try:
            return query_fn(client_order_id)
        except Exception:
            return None

    def reconcile_pending_orders(self) -> None:
        if self.store is None:
            return
        for pending in self.store.fetch_pending():
            status = self._query_adapter_status(pending.client_order_id)
            if status is None:
                continue
            if status.status in {"FILLED", "ACCEPTED", "CONFIRMED"}:
                self.store.mark_confirmed(pending.client_order_id)
                self._status_result_to_execution(status)
            elif status.status in {"DUPLICATE"}:
                self.store.mark_duplicate(pending.client_order_id)
                self._status_result_to_execution(status)

    def submit_order(self, approved_order: Mapping, *, reference_price: Optional[float] = None) -> ExecutedOrder:
        """Submit an approved order (mapping/object). Returns ExecutedOrder."""

        self.telemetry.submitted_orders += 1
        # robust field extraction
        symbol = approved_order.get("symbol") if isinstance(approved_order, Mapping) else getattr(approved_order, "symbol", "")
        direction = approved_order.get("direction") if isinstance(approved_order, Mapping) else getattr(approved_order, "direction", "LONG")
        requested_size = float(approved_order.get("size_pct", 0.0)) if isinstance(approved_order, Mapping) else float(getattr(approved_order, "size_pct", 0.0))
        approved_size = float(approved_order.get("size_pct", requested_size)) if isinstance(approved_order, Mapping) else float(getattr(approved_order, "size_pct", requested_size))
        entry_price = approved_order.get("entry_price") if isinstance(approved_order, Mapping) else getattr(approved_order, "entry_price", None)

        # Resolve reference price if missing
        if reference_price is None:
            if entry_price is None:
                raise ValueError("reference_price or order.entry_price is required")
            reference_price = float(entry_price)

        timestamp_ms = int(time.time() * 1000)

        # deterministically derive client_order_id for idempotency
        client_order_id = self._make_client_order_id(symbol=symbol, direction=direction, size_pct=approved_size, timestamp_ms=timestamp_ms)

        # persist before sending (if store exists)
        if self.store is not None:
            po = PersistedOrder(
                client_order_id=client_order_id,
                symbol=symbol,
                direction=direction,
                size_pct=approved_size,
                timestamp_utc=timestamp_ms,
                session_id=self.session_id,
                status="PENDING",
                metadata={"approved_order": dict(approved_order) if isinstance(approved_order, Mapping) else {}, "reference_price": reference_price},
            )
            self.store.insert_order(po)

        # attempt send with retries and jitter
        max_attempts = 3
        attempt = 0
        last_exc: Optional[Exception] = None
        while attempt <= max_attempts:
            try:
                # attach client_order_id into the payload so adapters can idempotently detect duplicates
                # Convert to dict if needed (handles both Pydantic models and plain mappings)
                if isinstance(approved_order, Mapping):
                    payload = dict(approved_order)
                else:
                    # For Pydantic models, use model_dump(); for other objects, extract known fields
                    if hasattr(approved_order, 'model_dump'):
                        payload = approved_order.model_dump()
                    else:
                        # Fallback: manually build dict from known fields
                        payload = {
                            "symbol": getattr(approved_order, "symbol", ""),
                            "direction": getattr(approved_order, "direction", "LONG"),
                            "size_pct": getattr(approved_order, "size_pct", 0.0),
                            "entry_price": getattr(approved_order, "entry_price", None),
                            "stop_loss_price": getattr(approved_order, "stop_loss_price", None),
                            "take_profit_price": getattr(approved_order, "take_profit_price", None),
                        }
                payload["client_order_id"] = client_order_id
                if str(payload.get("direction", "")) == "CLOSE_ALL":
                    self.telemetry.close_all_orders += 1
                executed = self._send_to_adapter_and_record(payload, reference_price=reference_price if reference_price is not None else entry_price)
                return executed
            except Exception as exc:
                last_exc = exc
                if isinstance(exc, DuplicateOrderError):
                    self.telemetry.duplicate_orders += 1
                    status = self._query_adapter_status(client_order_id)
                    if status is not None and status.status in {"FILLED", "ACCEPTED", "CONFIRMED", "DUPLICATE"}:
                        if self.store is not None:
                            self.store.mark_duplicate(client_order_id)
                        return self._status_result_to_execution(status)
                if attempt >= max_attempts:
                    self.telemetry.failed_submissions += 1
                    # mark failed and move to dead-letter if store present
                    if self.store is not None:
                        try:
                            self.store.mark_failed(client_order_id)
                        except Exception:
                            pass
                    raise
                # If the adapter can query order state, check before retrying to avoid duplicate submissions.
                status = self._query_adapter_status(client_order_id)
                if status is not None and status.status in {"FILLED", "ACCEPTED", "CONFIRMED"}:
                    if self.store is not None:
                        self.store.mark_confirmed(client_order_id)
                    return self._status_result_to_execution(status)
                # sleep backoff + jitter
                wait = self._backoff_and_jitter(attempt)
                self.telemetry.retry_attempts += 1
                time.sleep(wait)
                attempt += 1
        # unreachable
        raise RuntimeError("Order submission failed")

    def get_order(self, order_id: str) -> Optional[OrderRecord]:
        return self._orders.get(order_id)

    def get_execution(self, order_id: str) -> Optional[ExecutedOrder]:
        return self._executions.get(order_id)

    def get_telemetry(self) -> dict[str, object]:
        """Return a flat snapshot for reporting."""

        executions = list(self._executions.values())
        if executions:
            avg_fill_fraction = sum(exec_.filled_pct for exec_ in executions) / len(executions)
            avg_slippage = sum(abs(exec_.slippage_pct) for exec_ in executions) / len(executions)
            avg_fee = sum(exec_.fee_paid for exec_ in executions) / len(executions)
        else:
            avg_fill_fraction = 0.0
            avg_slippage = 0.0
            avg_fee = 0.0

        return {
            "submitted_orders": self.telemetry.submitted_orders,
            "executed_orders": self.telemetry.executed_orders,
            "duplicate_orders": self.telemetry.duplicate_orders,
            "retry_attempts": self.telemetry.retry_attempts,
            "failed_submissions": self.telemetry.failed_submissions,
            "close_all_orders": self.telemetry.close_all_orders,
            "average_fill_fraction": avg_fill_fraction,
            "average_slippage_pct": avg_slippage,
            "average_fee_paid": avg_fee,
        }
