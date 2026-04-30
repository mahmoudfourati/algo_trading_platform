"""Audit event helpers.

Emits structured audit events to stdout and optionally appends them to a log file.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional


def emit_audit_event(event_type: str, *, source: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """Phase 2.1 stub: print audit events to stdout.

    Later phases will publish these to the `audit.events` Kafka topic and persist via Layer 6.
    """

    event = {
        "event_type": event_type,
        "source": source,
        "timestamp_ms": int(time.time() * 1000),
        "payload": payload or {},
    }
    line = json.dumps(event, separators=(",", ":"), sort_keys=True)
    print(line)

    log_path = os.getenv("AUDIT_LOG_PATH")
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            # Audit logging is best-effort in Phase 2.1.
            pass
