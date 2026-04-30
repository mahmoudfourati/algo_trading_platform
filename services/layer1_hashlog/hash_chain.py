"""Validated-tick hash chain logger.

Appends an immutable hash chain entry per validated window for auditability.
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


GENESIS_HASH = "0" * 64


def _canonical_json_bytes(obj: Dict[str, Any]) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


def compute_tick_hash(
    *,
    symbol: str,
    consensus_mid: float,
    trust_score: float,
    received_timestamp_ms: int,
    previous_hash: str,
) -> str:
    payload = {
        "consensus_mid": float(consensus_mid),
        "previous_hash": str(previous_hash),
        "received_timestamp_ms": int(received_timestamp_ms),
        "symbol": str(symbol),
        "trust_score": float(trust_score),
    }
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return digest


@dataclass(frozen=True)
class HashChainEntry:
    symbol: str
    consensus_mid: float
    trust_score: float
    received_timestamp_ms: int
    previous_hash: str
    tick_hash: str

    def to_log_record(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "consensus_mid": self.consensus_mid,
            "trust_score": self.trust_score,
            "received_timestamp_ms": self.received_timestamp_ms,
            "previous_hash": self.previous_hash,
            "tick_hash": self.tick_hash,
        }


class HashChainLogger:
    """Async append-only hash chain log.

    Each append computes:
      tick_hash = SHA256(canonical_json({symbol, consensus_mid, trust_score, received_timestamp_ms, previous_hash}))

    And writes a JSONL record containing the above fields plus tick_hash.
    """

    def __init__(self, *, path: str | Path, buffer_max: int = 1000) -> None:
        self.path = Path(path)
        self._q: "queue.Queue[HashChainEntry]" = queue.Queue(maxsize=buffer_max)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._tip = GENESIS_HASH

    @property
    def tip(self) -> str:
        return self._tip

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="hash-chain-logger", daemon=True)
        self._thread.start()

    def stop(self, *, timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout_s)

        # Best-effort flush of remaining items synchronously.
        while True:
            try:
                entry = self._q.get_nowait()
            except queue.Empty:
                break
            self._write_entry(entry)

    def append(
        self,
        *,
        symbol: str,
        consensus_mid: float,
        trust_score: float,
        received_timestamp_ms: int,
        previous_hash: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """Append an entry.

        Returns (tick_hash, chain_ok) where chain_ok is True iff previous_hash matches the current tip.
        """

        prev = previous_hash if previous_hash is not None else self._tip
        chain_ok = prev == self._tip

        tick_hash = compute_tick_hash(
            symbol=symbol,
            consensus_mid=consensus_mid,
            trust_score=trust_score,
            received_timestamp_ms=received_timestamp_ms,
            previous_hash=prev,
        )
        entry = HashChainEntry(
            symbol=symbol,
            consensus_mid=consensus_mid,
            trust_score=trust_score,
            received_timestamp_ms=received_timestamp_ms,
            previous_hash=prev,
            tick_hash=tick_hash,
        )

        # Advance chain tip immediately (the log write is async).
        self._tip = tick_hash

        try:
            self._q.put_nowait(entry)
        except queue.Full:
            # Hash chain logging is best-effort; if saturated, we drop the entry.
            # (Blueprint allows dropping oldest during sustained outage; persistence is improved later.)
            pass

        return tick_hash, chain_ok

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                entry = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            self._write_entry(entry)

    def _write_entry(self, entry: HashChainEntry) -> None:
        line = json.dumps(entry.to_log_record(), separators=(",", ":"), sort_keys=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def verify_hash_chain(path: str | Path) -> Tuple[bool, str]:
    """Verify chain continuity + hash correctness.

    Returns (ok, message). On failure, message includes the failing line number.
    """

    p = Path(path)
    if not p.exists():
        return False, "log file does not exist"

    expected_prev = GENESIS_HASH

    with open(p, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                return False, f"line {idx}: invalid json: {e}"

            required = {"symbol", "consensus_mid", "trust_score", "received_timestamp_ms", "previous_hash", "tick_hash"}
            if not required.issubset(rec.keys()):
                return False, f"line {idx}: missing required fields"

            if rec["previous_hash"] != expected_prev:
                return False, f"line {idx}: previous_hash mismatch"

            recomputed = compute_tick_hash(
                symbol=rec["symbol"],
                consensus_mid=rec["consensus_mid"],
                trust_score=rec["trust_score"],
                received_timestamp_ms=rec["received_timestamp_ms"],
                previous_hash=rec["previous_hash"],
            )
            if rec["tick_hash"] != recomputed:
                return False, f"line {idx}: tick_hash mismatch"

            expected_prev = rec["tick_hash"]

    return True, "ok"
