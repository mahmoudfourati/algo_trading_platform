"""Deterministic time control utilities for backtest replay."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator
from unittest.mock import patch


@dataclass
class TimeController:
    """Track deterministic replay time during backtests."""

    current_time: datetime
    end_time: datetime
    speed: float = 1.0

    def __post_init__(self) -> None:
        if self.current_time.tzinfo is None:
            self.current_time = self.current_time.replace(tzinfo=timezone.utc)
        if self.end_time.tzinfo is None:
            self.end_time = self.end_time.replace(tzinfo=timezone.utc)

    def advance(self, seconds: float) -> None:
        """Advance controlled time by a scaled number of seconds."""
        self.current_time += timedelta(seconds=seconds * self.speed)

    def fast_forward(self, hours: float) -> None:
        """Jump forward by a number of hours in replay time."""
        self.current_time += timedelta(hours=hours)

    def sync_to(self, when: datetime) -> None:
        """Move the controlled clock to an absolute timestamp."""
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        self.current_time = when

    def now(self) -> datetime:
        """Return the current replay timestamp."""
        return self.current_time

    def now_ms(self) -> int:
        """Return the current replay timestamp in milliseconds."""
        return int(self.now().timestamp() * 1000)

    @contextmanager
    def patched(self) -> Iterator["TimeController"]:
        """Patch `time.time()` so replay code sees deterministic wall-clock time."""

        with patch("time.time", side_effect=lambda: self.now().timestamp()):
            yield self
