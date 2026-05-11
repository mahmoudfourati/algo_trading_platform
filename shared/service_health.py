"""Service health metrics for monitoring layer status.

Provides a simple way for each service to expose its health/liveness status
to Prometheus for monitoring which layers are up or down.
"""

from __future__ import annotations

import os
from prometheus_client import Gauge


# Global service health gauge
# Value of 1 = service is running and healthy
# Value of 0 or missing = service is down or unreachable
_service_health = Gauge(
    "service_health",
    "Service health status (1=up, 0=down)",
    ["service_name", "layer"]
)

# System operational mode gauge
# 0 = paper trading, 1 = live trading, 2 = backtest, 3 = maintenance
_system_operational_mode = Gauge(
    "system_operational_mode",
    "System operational mode (0=paper, 1=live, 2=backtest, 3=maintenance)"
)


def mark_service_healthy(service_name: str, layer: str) -> None:
    """Mark this service as healthy/running.
    
    Should be called once during service startup after initialization.
    
    Args:
        service_name: Name of the service (e.g., "layer1_ingestion")
        layer: Layer number (e.g., "layer1", "layer2", etc.)
    """
    _service_health.labels(service_name=service_name, layer=layer).set(1)


def mark_service_unhealthy(service_name: str, layer: str) -> None:
    """Mark this service as unhealthy/stopping.
    
    Optional - can be called during graceful shutdown.
    
    Args:
        service_name: Name of the service (e.g., "layer1_ingestion")
        layer: Layer number (e.g., "layer1", "layer2", etc.)
    """
    _service_health.labels(service_name=service_name, layer=layer).set(0)


def set_operational_mode_from_env() -> None:
    """Set system operational mode from OPERATIONAL_MODE environment variable.
    
    Valid values:
    - "paper" or "PAPER" -> 0 (paper trading)
    - "live" or "LIVE" -> 1 (live trading)
    - "backtest" or "BACKTEST" -> 2 (backtest mode)
    - "maintenance" or "MAINTENANCE" -> 3 (maintenance mode)
    
    Defaults to paper trading (0) if not set or invalid.
    """
    mode_str = os.getenv("OPERATIONAL_MODE", "paper").lower()
    
    mode_map = {
        "paper": 0,
        "live": 1,
        "backtest": 2,
        "maintenance": 3
    }
    
    mode_value = mode_map.get(mode_str, 0)
    _system_operational_mode.set(mode_value)

