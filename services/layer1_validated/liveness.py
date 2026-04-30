"""Exchange liveness monitor.

Tracks last-seen ticks per exchange and emits audit events when exchanges
go silent beyond expected intervals.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List


EXPECTED_INTERVALS_MS: Dict[str, float] = {
    "binance": 500,
    "coinbase": 5_000,
    "kraken": 7_500,
    "okx": 500,
    "bybit": 500,
}

SILENCE_MULTIPLIER = 3.0


class ExchangeLivenessMonitor:
    def __init__(self, *, sources: List[str], audit_fn: Callable[[str, Dict], None]):
        self.sources = list(sources)
        self.audit_fn = audit_fn
        self._last_seen: Dict[str, float] = {}
        self._alerted: Dict[str, bool] = {}

    def record_tick(self, source: str) -> None:
        now = time.time() * 1000
        if self._alerted.get(source):
            self.audit_fn(
                "exchange_recovered",
                {"source": source, "silent_ms": now - self._last_seen.get(source, now)},
            )
            self._alerted[source] = False
        self._last_seen[source] = now

    def check_all(self) -> Dict[str, float]:
        now = time.time() * 1000
        overdue: Dict[str, float] = {}

        for source in self.sources:
            last = self._last_seen.get(source)
            if last is None:
                continue

            silence_ms = now - last
            threshold = EXPECTED_INTERVALS_MS.get(source, 10_000) * SILENCE_MULTIPLIER
            if silence_ms > threshold:
                overdue[source] = silence_ms
                if not self._alerted.get(source):
                    self.audit_fn(
                        "exchange_silent",
                        {
                            "source": source,
                            "silence_ms": silence_ms,
                            "threshold_ms": threshold,
                        },
                    )
                    self._alerted[source] = True

        return overdue
