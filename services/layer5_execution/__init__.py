"""Layer 5 execution engine package.

Provides a simulated execution engine and adapters used by the backtest
and later the live execution plumbing.
"""

from .engine import ExecutionEngine, ExecutedOrder, OrderRecord
from .adapters import SimulatedExecutionAdapter

__all__ = ["ExecutionEngine", "ExecutedOrder", "OrderRecord", "SimulatedExecutionAdapter"]
