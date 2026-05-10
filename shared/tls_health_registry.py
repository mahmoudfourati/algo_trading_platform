"""Thread-safe TLS health registry.

Provides a shared, non-blocking, async-safe registry for tracking TLS health
status per exchange. Used by ingestion adapters to mark health and by the
validated service to read cached health without blocking the hot path.
"""

from __future__ import annotations

import threading
from typing import Dict


class TlsHealthRegistry:
    """Thread-safe TLS health registry.
    
    Tracks TLS health status per exchange. All operations are non-blocking
    and safe for concurrent access from multiple threads/async contexts.
    
    Design:
    - Uses threading.Lock for thread safety
    - All operations are O(1)
    - No blocking I/O in any method
    - Defaults to healthy (optimistic) for unknown exchanges
    """
    
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._health: Dict[str, bool] = {}
    
    def mark_healthy(self, exchange_id: str) -> None:
        """Mark an exchange as TLS-healthy (pin verified successfully)."""
        with self._lock:
            self._health[exchange_id] = True
    
    def mark_unhealthy(self, exchange_id: str, reason: str = "") -> None:
        """Mark an exchange as TLS-unhealthy (pin mismatch or verification failed).
        
        Args:
            exchange_id: Exchange identifier
            reason: Optional reason string (for logging/debugging, not stored)
        """
        with self._lock:
            self._health[exchange_id] = False
    
    def is_healthy(self, exchange_id: str) -> bool:
        """Check if an exchange is TLS-healthy.
        
        Returns True if:
        - Exchange was explicitly marked healthy
        
        Returns False if:
        - Exchange was explicitly marked unhealthy
        - Exchange has never been checked (pessimistic default for security)
        """
        with self._lock:
            return self._health.get(exchange_id, False)
    
    def get_all_health(self) -> Dict[str, bool]:
        """Get a snapshot of all exchange health states.
        
        Returns a copy of the health dict (safe to iterate without holding lock).
        """
        with self._lock:
            return dict(self._health)
    
    def reset(self) -> None:
        """Reset all health states (primarily for testing)."""
        with self._lock:
            self._health.clear()


# Global singleton registry
_global_registry = TlsHealthRegistry()


def get_tls_health_registry() -> TlsHealthRegistry:
    """Get the global TLS health registry singleton."""
    return _global_registry
