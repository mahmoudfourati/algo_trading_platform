"""Unit tests for the Phase 8 execution engine (simulated adapter).
"""

from __future__ import annotations

from services.layer5_execution.engine import ExecutionEngine
from services.layer5_execution.adapters import SimulatedExecutionAdapter


def test_simulated_adapter_full_fill_and_fee() -> None:
    adapter = SimulatedExecutionAdapter(slippage_pct=0.001, fee_pct=0.001)
    engine = ExecutionEngine(adapter=adapter, portfolio_value=1000.0)

    fake_order = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "size_pct": 0.1,
        "entry_price": 50000.0,
    }

    executed = engine.submit_order(fake_order, reference_price=50000.0)

    assert executed.filled_pct > 0.0
    assert executed.avg_fill_price == 50000.0 * (1.0 + adapter.slippage_pct)
    assert executed.fee_paid > 0.0


def test_simulated_adapter_partial_fill_behavior() -> None:
    adapter = SimulatedExecutionAdapter(slippage_pct=0.001, fee_pct=0.001, partial_fill_threshold=0.2)
    engine = ExecutionEngine(adapter=adapter, portfolio_value=1000.0)

    fake_order = {"symbol": "BTCUSDT", "direction": "LONG", "size_pct": 0.5, "entry_price": 100.0}

    executed = engine.submit_order(fake_order, reference_price=100.0)

    # since size_pct (0.5) > partial_fill_threshold (0.2), expect only 0.2 filled
    assert executed.filled_pct == 0.2
    assert executed.note == "partial"
