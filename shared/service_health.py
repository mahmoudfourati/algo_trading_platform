"""Service health metrics for monitoring layer status.

Provides a simple way for each service to expose its health/liveness status
to Prometheus for monitoring which layers are up or down.
"""

from __future__ import annotations

from prometheus_client import Gauge


# Global service health gauge
# Value of 1 = service is running and healthy
# Value of 0 or missing = service is down or unreachable
_service_health = Gauge(
    "service_health",
    "Service health status (1=up, 0=down)",
    ["service_name", "layer"]
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
