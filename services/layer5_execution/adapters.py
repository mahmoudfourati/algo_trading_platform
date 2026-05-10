"""Execution adapters: simulated (backtesting) and Binance (live/testnet).

SimulatedExecutionAdapter: deterministic, in-process, for unit tests and backtests.
BinanceExecutionAdapter: connects to Binance Futures API (testnet or live).
Both implement the same interface: execute() → SimulatedFillResult, get_order_status() → OrderStatusResult.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import time
from typing import Dict, Mapping, Optional
from urllib.parse import urlencode

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class DuplicateOrderError(RuntimeError):
    """Raised when the same client_order_id is submitted more than once."""


@dataclass(frozen=True)
class OrderStatusResult:
    client_order_id: str
    status: str
    filled_pct: float = 0.0
    avg_fill_price: float = 0.0
    fee_paid: float = 0.0
    latency_ms: float = 0.0
    note: Optional[str] = None


@dataclass(frozen=True)
class SimulatedFillResult:
    filled_pct: float
    avg_fill_price: float
    fee_paid: float
    slippage_pct: float
    latency_ms: float = 0.0
    note: Optional[str] = None


class SimulatedExecutionAdapter:
    """Simple deterministic adapter.

    Parameters are percentages (0-1): `slippage_pct`, `fee_pct`.
    `partial_fill_threshold` controls when large orders are partially filled.
    """

    def __init__(
        self,
        *,
        slippage_pct: float = 0.0005,
        fee_pct: float = 0.00075,
        partial_fill_threshold: float = 0.5,
        partial_fill_ratio: float = 0.0,
        latency_ms_base: float = 15.0,
        latency_ms_per_size_pct: float = 40.0,
        latency_ms_jitter: float = 25.0,
        fee_schedule: Optional[Mapping[str, float]] = None,
    ) -> None:
        self.slippage_pct = float(slippage_pct)
        self.fee_pct = float(fee_pct)
        self.partial_fill_threshold = float(partial_fill_threshold)
        self.partial_fill_ratio = float(partial_fill_ratio)
        self.latency_ms_base = float(latency_ms_base)
        self.latency_ms_per_size_pct = float(latency_ms_per_size_pct)
        self.latency_ms_jitter = float(latency_ms_jitter)
        self.fee_schedule = dict(fee_schedule or {})
        self._status: Dict[str, OrderStatusResult] = {}

    def _deterministic_latency(self, order: Mapping) -> float:
        client_order_id = str(order.get("client_order_id", ""))
        seed = f"{client_order_id}|{order.get('symbol', '')}|{order.get('direction', '')}|{order.get('size_pct', 0.0)}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        jitter_unit = int(digest[:8], 16) / 0xFFFFFFFF
        jitter = (jitter_unit * 2.0 - 1.0) * self.latency_ms_jitter
        size_pct = float(order.get("size_pct", 0.0))
        return max(0.0, self.latency_ms_base + size_pct * self.latency_ms_per_size_pct + jitter)

    def _fee_pct_for(self, order: Mapping) -> float:
        exchange_id = str(order.get("exchange_id", order.get("primary_exchange", "default")))
        return float(self.fee_schedule.get(exchange_id, self.fee_pct))

    def get_order_status(self, client_order_id: str) -> Optional[OrderStatusResult]:
        return self._status.get(client_order_id)

    def execute(self, order: Mapping, reference_price: float) -> SimulatedFillResult:
        """Execute an order mapping and return a SimulatedFillResult.

        The adapter accepts either a mapping or a dataclass-like object with
        attributes used below. It computes a fill price by applying slippage
        in the direction of the trade and charges a fee on the notional.
        """

        # Robust field extraction: works with both dicts and dataclass objects
        is_mapping = isinstance(order, Mapping)
        if is_mapping:
            client_order_id = str(order.get("client_order_id", ""))
            size_pct = float(order.get("size_pct", 0.0))
            direction = order.get("direction", "LONG")
        else:
            client_order_id = str(getattr(order, "client_order_id", ""))
            size_pct = float(getattr(order, "size_pct", 0.0))
            direction = getattr(order, "direction", "LONG")

        if client_order_id and client_order_id in self._status:
            raise DuplicateOrderError(f"duplicate client_order_id={client_order_id}")

        # Simulate slippage: push price by slippage_pct in adverse direction
        if direction == "LONG":
            fill_price = reference_price * (1.0 + self.slippage_pct)
            slippage = self.slippage_pct
        else:
            fill_price = reference_price * (1.0 - self.slippage_pct)
            slippage = -self.slippage_pct

        # Partial fills for large sized orders.
        if size_pct > self.partial_fill_threshold:
            excess = size_pct - self.partial_fill_threshold
            filled = min(size_pct, self.partial_fill_threshold + excess * self.partial_fill_ratio)
            note = "partial"
        else:
            filled = size_pct
            note = "full"

        notional = filled * float(order.get("portfolio_value", 1.0))
        # fee should be applied to the notional (quote currency); do NOT multiply
        # by price again — that double-applies price and overstates fees.
        fee_paid = abs(notional) * self._fee_pct_for(order)
        latency_ms = self._deterministic_latency(order)

        if client_order_id:
            self._status[client_order_id] = OrderStatusResult(
                client_order_id=client_order_id,
                status="FILLED",
                filled_pct=filled,
                avg_fill_price=fill_price,
                fee_paid=fee_paid,
                latency_ms=latency_ms,
                note=note,
            )

        return SimulatedFillResult(filled_pct=filled, avg_fill_price=fill_price, fee_paid=fee_paid, slippage_pct=slippage, latency_ms=latency_ms, note=note)


class BinanceExecutionAdapter:
    """Live execution adapter for Binance Futures (testnet or live).
    
    Implements the same interface as SimulatedExecutionAdapter:
    - execute(order, reference_price) → SimulatedFillResult
    - get_order_status(client_order_id) → Optional[OrderStatusResult]
    
    Requires httpx for HTTP requests. Set EXECUTION_ADAPTER_TYPE=binance,
    BINANCE_API_KEY, BINANCE_API_SECRET, and BINANCE_TESTNET=true/false.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        base_url: Optional[str] = None,
    ) -> None:
        if not HAS_HTTPX:
            raise ImportError("httpx is required for BinanceExecutionAdapter; install with: pip install httpx")
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        if base_url is None:
            self.base_url = (
                "https://testnet.binancefuture.com" if testnet
                else "https://fapi.binance.com"
            )
        else:
            self.base_url = base_url
        
        self.http = httpx.Client(timeout=10.0)
        self._status: Dict[str, OrderStatusResult] = {}
        self._fee_maker = 0.0002  # Binance futures default maker fee
        self._fee_taker = 0.0004  # Binance futures default taker fee

    def _sign(self, query_string: str) -> str:
        """HMAC SHA256 signature for Binance API."""
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _binance_symbol(self, symbol: str) -> str:
        """Normalize symbol: 'BTC-USDT' → 'BTCUSDT'."""
        return symbol.replace("-", "").upper()

    def execute(self, order: Mapping, reference_price: float) -> SimulatedFillResult:
        """Submit market order to Binance Futures and return fill result.
        
        Raises DuplicateOrderError if client_order_id already exists.
        Raises RuntimeError if order submission fails.
        """
        
        symbol = order.get("symbol", "BTC-USDT")
        direction = order.get("direction", "LONG")
        size_pct = float(order.get("size_pct", 0.0))
        client_order_id = order.get("client_order_id", "")
        portfolio_value = float(order.get("portfolio_value", 1.0))
        
        if client_order_id and client_order_id in self._status:
            raise DuplicateOrderError(f"duplicate client_order_id={client_order_id}")
        
        if size_pct <= 0.0:
            raise ValueError("size_pct must be positive")
        
        # Build Binance order request
        binance_symbol = self._binance_symbol(symbol)
        quantity = size_pct * portfolio_value / reference_price
        side = "BUY" if direction == "LONG" else "SELL"
        
        params = {
            "symbol": binance_symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{quantity:.8f}",
            "clientOrderId": client_order_id,
            "timestamp": int(time.time() * 1000),
        }
        
        # Sign and send
        query_string = urlencode(params)
        params["signature"] = self._sign(query_string)
        
        try:
            response = self.http.post(
                f"{self.base_url}/fapi/v1/order",
                headers={"X-MBX-APIKEY": self.api_key},
                params=params,
            )
            response.raise_for_status()
            result = response.json()
        except Exception as exc:
            raise RuntimeError(f"Binance order submission failed: {exc}")
        
        # Parse Binance response
        executed_qty = float(result.get("executedQty", 0.0))
        avg_price = float(result.get("avgPrice", reference_price))
        
        # Calculate fee (Binance charges on notional)
        notional = executed_qty * avg_price
        fee = notional * self._fee_taker
        
        # Calculate slippage vs reference price
        if direction == "LONG":
            slippage_pct = (avg_price - reference_price) / reference_price if reference_price > 0 else 0.0
        else:
            slippage_pct = (reference_price - avg_price) / reference_price if reference_price > 0 else 0.0
        
        filled_pct = executed_qty / quantity if quantity > 0 else 0.0
        fill_note = "full" if filled_pct >= 0.99 else "partial"
        
        # Store status for reconciliation
        if client_order_id:
            self._status[client_order_id] = OrderStatusResult(
                client_order_id=client_order_id,
                status=result.get("status", "FILLED"),
                filled_pct=filled_pct,
                avg_fill_price=avg_price,
                fee_paid=fee,
                note=fill_note,
            )
        
        return SimulatedFillResult(
            filled_pct=filled_pct,
            avg_fill_price=avg_price,
            fee_paid=fee,
            slippage_pct=slippage_pct,
            note=fill_note,
        )

    def get_order_status(self, client_order_id: str) -> Optional[OrderStatusResult]:
        """Query order status from local cache.
        
        In a production system, this would query the Binance API.
        For now, returns cached status from execute() calls.
        """
        return self._status.get(client_order_id)
