"""Validated-tick hash chain logger.

Appends an immutable hash chain entry per validated window for auditability.

Features:
- Automatic file rotation at configurable size (default 100MB)
- Compression of old files with gzip (10x compression)
- Automatic cleanup of files older than retention period (default 7 days)
- Startup verification of last N hashes (default 1000)
- Cross-file continuity (first entry in new file references last hash from previous file)
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from prometheus_client import Counter, Gauge

from shared.schemas import ExchangeId


GENESIS_HASH = "0" * 64
DEFAULT_MAX_FILE_SIZE_MB = 100
DEFAULT_RETENTION_DAYS = 7
DEFAULT_VERIFY_ON_STARTUP = 1000

# Metrics
_hashchain_entries_total = Counter(
    "hashchain_entries_total",
    "Total hash chain entries written",
    ["symbol"],
)

_hashchain_rotations_total = Counter(
    "hashchain_rotations_total",
    "Total file rotations",
)

_hashchain_compressions_total = Counter(
    "hashchain_compressions_total",
    "Total file compressions",
)

_hashchain_deletions_total = Counter(
    "hashchain_deletions_total",
    "Total file deletions",
)

_hashchain_current_file_size_bytes = Gauge(
    "hashchain_current_file_size_bytes",
    "Current hash chain file size in bytes",
)

_hashchain_verification_status = Gauge(
    "hashchain_verification_status",
    "Hash chain verification status (1=ok, 0=failed, -1=not_started)",
)

_hashchain_queue_depth = Gauge(
    "hashchain_queue_depth",
    "Current hash chain queue depth",
)


def _canonical_json_bytes(obj: Dict[str, Any]) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


def compute_tick_hash(
    *,
    symbol: str,
    primary_exchange: ExchangeId,
    primary_mid_price: float,
    consensus_mid: float,
    used_sources: list[ExchangeId],
    divergent_sources: list[ExchangeId],
    trust_score: float,
    received_timestamp_ms: int,
    previous_hash: str,
) -> str:
    payload = {
        "consensus_mid": float(consensus_mid),
        "divergent_sources": [str(x) for x in divergent_sources],
        "primary_exchange": str(primary_exchange),
        "primary_mid_price": float(primary_mid_price),
        "previous_hash": str(previous_hash),
        "received_timestamp_ms": int(received_timestamp_ms),
        "symbol": str(symbol),
        "used_sources": [str(x) for x in used_sources],
        "trust_score": float(trust_score),
    }
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return digest


@dataclass(frozen=True)
class HashChainEntry:
    symbol: str
    primary_exchange: ExchangeId
    primary_mid_price: float
    consensus_mid: float
    used_sources: list[ExchangeId]
    divergent_sources: list[ExchangeId]
    trust_score: float
    received_timestamp_ms: int
    previous_hash: str
    tick_hash: str

    def to_log_record(self) -> Dict[str, Any]:
        return {
            "consensus_mid": self.consensus_mid,
            "divergent_sources": [str(x) for x in self.divergent_sources],
            "primary_exchange": self.primary_exchange,
            "primary_mid_price": self.primary_mid_price,
            "previous_hash": self.previous_hash,
            "received_timestamp_ms": self.received_timestamp_ms,
            "symbol": self.symbol,
            "used_sources": [str(x) for x in self.used_sources],
            "trust_score": self.trust_score,
            "tick_hash": self.tick_hash,
        }


class HashChainLogger:
    """Async append-only hash chain log with rotation and compression.

    Each append computes:
      tick_hash = SHA256(canonical_json({symbol, consensus_mid, trust_score, received_timestamp_ms, previous_hash}))

    And writes a JSONL record containing the above fields plus tick_hash.

    Features:
    - Automatic rotation when file reaches max_file_size_mb
    - Compression of rotated files with gzip
    - Automatic cleanup of files older than retention_days
    - Startup verification of last verify_on_startup hashes
    - Cross-file continuity tracking
    """

    def __init__(
        self,
        *,
        path: str | Path,
        buffer_max: int = 1000,
        max_file_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        verify_on_startup: int = DEFAULT_VERIFY_ON_STARTUP,
    ) -> None:
        self.base_path = Path(path)
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.retention_days = retention_days
        self.verify_on_startup = verify_on_startup
        
        self._q: "queue.Queue[HashChainEntry]" = queue.Queue(maxsize=buffer_max)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._tip = GENESIS_HASH
        self._current_file: Optional[Path] = None
        self._current_file_handle: Optional[Any] = None
        self._sequence_number = 1
        
        # Metrics
        self.total_entries = 0
        self.total_rotations = 0
        self.total_compressions = 0
        self.total_deletions = 0
        self.verification_status = "not_started"
        self.verification_message = ""

    @property
    def tip(self) -> str:
        return self._tip

    def _get_file_pattern(self) -> str:
        """Get the base filename pattern for hash chain files."""
        base_name = self.base_path.stem
        return f"{base_name}_*.jsonl"

    def _get_current_file_path(self) -> Path:
        """Generate path for current hash chain file."""
        base_name = self.base_path.stem
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        return self.base_path.parent / f"{base_name}_{timestamp}_{self._sequence_number:03d}.jsonl"

    def _find_latest_file(self) -> Optional[Path]:
        """Find the most recent hash chain file."""
        pattern = self._get_file_pattern()
        files = sorted(self.base_path.parent.glob(pattern))
        if not files:
            return None
        return files[-1]

    def _load_tip_from_disk(self) -> str:
        """Load the last hash from the most recent file."""
        latest_file = self._find_latest_file()
        if not latest_file or not latest_file.exists():
            return GENESIS_HASH

        # Read last line
        last_hash = GENESIS_HASH
        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                            last_hash = rec.get("tick_hash", last_hash)
                        except json.JSONDecodeError:
                            continue
        except Exception:
            pass

        return last_hash

    def _verify_recent_hashes(self) -> Tuple[bool, str]:
        """Verify the last N hashes from the most recent file."""
        if self.verify_on_startup <= 0:
            return True, "verification disabled"

        latest_file = self._find_latest_file()
        if not latest_file or not latest_file.exists():
            return True, "no existing file to verify"

        # Read last N lines
        lines = []
        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            return False, f"failed to read file: {e}"

        # Take last N lines
        lines_to_verify = lines[-self.verify_on_startup:] if len(lines) > self.verify_on_startup else lines

        if not lines_to_verify:
            return True, "no entries to verify"

        # Verify chain continuity
        expected_prev = None
        for idx, line in enumerate(lines_to_verify):
            line = line.strip()
            if not line:
                continue

            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                return False, f"entry {idx}: invalid json: {e}"

            # First entry: get previous_hash as starting point
            if expected_prev is None:
                expected_prev = rec.get("previous_hash")
                if expected_prev is None:
                    return False, f"entry {idx}: missing previous_hash"

            # Verify previous_hash matches
            if rec.get("previous_hash") != expected_prev:
                return False, f"entry {idx}: previous_hash mismatch (expected {expected_prev}, got {rec.get('previous_hash')})"

            # Verify tick_hash computation
            recomputed = compute_tick_hash(
                symbol=rec["symbol"],
                primary_exchange=rec["primary_exchange"],
                primary_mid_price=rec["primary_mid_price"],
                consensus_mid=rec["consensus_mid"],
                used_sources=rec["used_sources"],
                divergent_sources=rec["divergent_sources"],
                trust_score=rec["trust_score"],
                received_timestamp_ms=rec["received_timestamp_ms"],
                previous_hash=rec["previous_hash"],
            )
            if rec["tick_hash"] != recomputed:
                return False, f"entry {idx}: tick_hash mismatch"

            expected_prev = rec["tick_hash"]

        return True, f"verified {len(lines_to_verify)} entries"

    def _extract_sequence_from_filename(self, path: Path) -> int:
        """Extract sequence number from filename."""
        match = re.search(r"_(\d{3})\.jsonl", path.name)
        if match:
            return int(match.group(1))
        return 0

    def _rotate_if_needed(self) -> None:
        """Rotate to a new file if current file exceeds max size."""
        if self._current_file is None:
            return

        try:
            file_size = self._current_file.stat().st_size
            if file_size >= self.max_file_size_bytes:
                # Close current file
                if self._current_file_handle:
                    self._current_file_handle.close()
                    self._current_file_handle = None

                # Compress the rotated file
                self._compress_file(self._current_file)
                self.total_compressions += 1
                _hashchain_compressions_total.inc()

                # Increment sequence number
                self._sequence_number += 1
                self.total_rotations += 1
                _hashchain_rotations_total.inc()

                # Open new file
                self._current_file = self._get_current_file_path()
                self._current_file_handle = open(self._current_file, "a", encoding="utf-8")
                
                # Update file size metric
                _hashchain_current_file_size_bytes.set(0)

        except Exception:
            # If rotation fails, continue with current file
            pass

    def _compress_file(self, path: Path) -> None:
        """Compress a file with gzip."""
        try:
            compressed_path = path.with_suffix(path.suffix + ".gz")
            with open(path, "rb") as f_in:
                with gzip.open(compressed_path, "wb") as f_out:
                    f_out.writelines(f_in)
            # Delete original file after successful compression
            path.unlink()
        except Exception:
            # If compression fails, keep the original file
            pass

    def _cleanup_old_files(self) -> None:
        """Delete files older than retention period."""
        if self.retention_days <= 0:
            return

        cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)
        pattern = self._get_file_pattern()

        try:
            for file_path in self.base_path.parent.glob(pattern):
                # Also check for compressed files
                for check_path in [file_path, file_path.with_suffix(file_path.suffix + ".gz")]:
                    if not check_path.exists():
                        continue

                    # Extract date from filename
                    match = re.search(r"_(\d{8})_", check_path.name)
                    if match:
                        file_date_str = match.group(1)
                        try:
                            file_date = datetime.strptime(file_date_str, "%Y%m%d")
                            if file_date < cutoff_date:
                                check_path.unlink()
                                self.total_deletions += 1
                                _hashchain_deletions_total.inc()
                        except ValueError:
                            continue
        except Exception:
            # If cleanup fails, continue
            pass

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.base_path.parent.mkdir(parents=True, exist_ok=True)

        # Verify recent hashes on startup
        ok, msg = self._verify_recent_hashes()
        self.verification_status = "ok" if ok else "failed"
        self.verification_message = msg

        # Update verification metric
        if ok:
            _hashchain_verification_status.set(1)
        else:
            _hashchain_verification_status.set(0)
            # Log warning but continue (don't halt the system)
            print(f"WARNING: Hash chain verification failed: {msg}")

        # Load tip from disk
        self._tip = self._load_tip_from_disk()

        # Find latest file and extract sequence number
        latest_file = self._find_latest_file()
        if latest_file:
            self._sequence_number = self._extract_sequence_from_filename(latest_file) + 1
            # Check if we should continue with the latest file or start a new one
            try:
                file_size = latest_file.stat().st_size
                if file_size < self.max_file_size_bytes:
                    # Continue with existing file
                    self._current_file = latest_file
                    self._sequence_number = self._extract_sequence_from_filename(latest_file)
                else:
                    # Start new file
                    self._current_file = self._get_current_file_path()
            except Exception:
                self._current_file = self._get_current_file_path()
        else:
            self._current_file = self._get_current_file_path()

        # Open file handle
        self._current_file_handle = open(self._current_file, "a", encoding="utf-8")

        # Update file size metric
        try:
            _hashchain_current_file_size_bytes.set(self._current_file.stat().st_size)
        except Exception:
            pass

        # Cleanup old files
        self._cleanup_old_files()

        # Start background thread
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

        # Close file handle
        if self._current_file_handle:
            self._current_file_handle.close()
            self._current_file_handle = None

    def append(
        self,
        *,
        symbol: str,
        consensus_mid: float,
        trust_score: float,
        received_timestamp_ms: int,
        primary_exchange: Optional[ExchangeId] = None,
        primary_mid_price: Optional[float] = None,
        used_sources: Optional[list[ExchangeId]] = None,
        divergent_sources: Optional[list[ExchangeId]] = None,
        previous_hash: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """Append an entry.

        Returns (tick_hash, chain_ok) where chain_ok is True iff previous_hash matches the current tip.
        """

        prev = previous_hash if previous_hash is not None else self._tip

        # Backwards-compatible defaults: if caller omitted primary_exchange/primary_mid/used/divergent
        if primary_exchange is None:
            primary_exchange = "binance"
        if primary_mid_price is None:
            primary_mid_price = float(consensus_mid)
        if used_sources is None:
            used_sources = []
        if divergent_sources is None:
            divergent_sources = []
        chain_ok = prev == self._tip

        tick_hash = compute_tick_hash(
            symbol=symbol,
            primary_exchange=primary_exchange,
            primary_mid_price=primary_mid_price,
            consensus_mid=consensus_mid,
            used_sources=used_sources,
            divergent_sources=divergent_sources,
            trust_score=trust_score,
            received_timestamp_ms=received_timestamp_ms,
            previous_hash=prev,
        )
        entry = HashChainEntry(
            symbol=symbol,
            primary_exchange=primary_exchange,
            primary_mid_price=primary_mid_price,
            consensus_mid=consensus_mid,
            used_sources=used_sources,
            divergent_sources=divergent_sources,
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
                # Update queue depth metric
                _hashchain_queue_depth.set(self._q.qsize())
                continue
            
            self._write_entry(entry)
            
            # Update queue depth metric
            _hashchain_queue_depth.set(self._q.qsize())
            
            # Check if rotation is needed
            self._rotate_if_needed()
            
            # Periodically cleanup old files (every 1000 entries)
            if self.total_entries % 1000 == 0:
                self._cleanup_old_files()

    def _write_entry(self, entry: HashChainEntry) -> None:
        if self._current_file_handle is None:
            return

        line = json.dumps(entry.to_log_record(), separators=(",", ":"), sort_keys=True)
        try:
            self._current_file_handle.write(line + "\n")
            self._current_file_handle.flush()  # Ensure data is written to disk
            self.total_entries += 1
            
            # Update metrics
            _hashchain_entries_total.labels(symbol=entry.symbol).inc()
            
            # Update file size metric
            try:
                _hashchain_current_file_size_bytes.set(self._current_file.stat().st_size)
            except Exception:
                pass
                
        except Exception:
            # If write fails, try to reopen the file
            try:
                if self._current_file_handle:
                    self._current_file_handle.close()
                self._current_file_handle = open(self._current_file, "a", encoding="utf-8")
            except Exception:
                pass


def verify_hash_chain(path: str | Path, max_entries: Optional[int] = None, expected_first_hash: Optional[str] = None) -> Tuple[bool, str]:
    """Verify chain continuity + hash correctness.

    Args:
        path: Path to hash chain file (can be .jsonl or .jsonl.gz)
        max_entries: Maximum number of entries to verify (None = all)
        expected_first_hash: Expected previous_hash for first entry (None = don't check)

    Returns (ok, message). On failure, message includes the failing line number.
    """

    p = Path(path)
    if not p.exists():
        return False, "log file does not exist"

    expected_prev = expected_first_hash  # Will be set from first entry if None
    entries_verified = 0

    # Determine if file is compressed
    is_compressed = p.suffix == ".gz"

    try:
        if is_compressed:
            f = gzip.open(p, "rt", encoding="utf-8")
        else:
            f = open(p, "r", encoding="utf-8")

        with f:
            for idx, line in enumerate(f, start=1):
                if max_entries and entries_verified >= max_entries:
                    break

                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    return False, f"line {idx}: invalid json: {e}"

                required = {
                    "symbol",
                    "primary_exchange",
                    "primary_mid_price",
                    "consensus_mid",
                    "used_sources",
                    "divergent_sources",
                    "trust_score",
                    "received_timestamp_ms",
                    "previous_hash",
                    "tick_hash",
                }
                if not required.issubset(rec.keys()):
                    return False, f"line {idx}: missing required fields"

                # For first entry, set expected_prev if not provided
                if expected_prev is None:
                    expected_prev = rec["previous_hash"]

                if rec["previous_hash"] != expected_prev:
                    return False, f"line {idx}: previous_hash mismatch (expected {expected_prev}, got {rec['previous_hash']})"

                recomputed = compute_tick_hash(
                    symbol=rec["symbol"],
                    primary_exchange=rec["primary_exchange"],
                    primary_mid_price=rec["primary_mid_price"],
                    consensus_mid=rec["consensus_mid"],
                    used_sources=rec["used_sources"],
                    divergent_sources=rec["divergent_sources"],
                    trust_score=rec["trust_score"],
                    received_timestamp_ms=rec["received_timestamp_ms"],
                    previous_hash=rec["previous_hash"],
                )
                if rec["tick_hash"] != recomputed:
                    return False, f"line {idx}: tick_hash mismatch"

                expected_prev = rec["tick_hash"]
                entries_verified += 1

    except Exception as e:
        return False, f"error reading file: {e}"

    return True, f"verified {entries_verified} entries"


def verify_hash_chain_directory(directory: str | Path, pattern: str = "*.jsonl*") -> Tuple[bool, List[str]]:
    """Verify all hash chain files in a directory.

    Args:
        directory: Directory containing hash chain files
        pattern: Glob pattern for files to verify (default: *.jsonl*)

    Returns (ok, messages) where messages is a list of verification results per file.
    
    Note: This function verifies each file individually but does NOT check cross-file
    continuity because files may be rotated at any time and the first entry in a new
    file will have a previous_hash from the last entry of the previous file, which
    requires reading all files in sequence.
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        return False, ["directory does not exist"]

    files = sorted(dir_path.glob(pattern))
    if not files:
        return False, ["no hash chain files found"]

    messages = []
    all_ok = True

    for file_path in files:
        ok, msg = verify_hash_chain(file_path)
        
        if ok:
            messages.append(f"{file_path.name}: OK - {msg}")
        else:
            all_ok = False
            messages.append(f"{file_path.name}: FAILED - {msg}")

    return all_ok, messages


def _get_first_previous_hash(path: Path) -> str:
    """Get the previous_hash from the first entry in a file."""
    is_compressed = path.suffix == ".gz"
    
    try:
        if is_compressed:
            f = gzip.open(path, "rt", encoding="utf-8")
        else:
            f = open(path, "r", encoding="utf-8")

        with f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    return rec.get("previous_hash", GENESIS_HASH)
    except Exception:
        pass
    
    return GENESIS_HASH


def _get_last_tick_hash(path: Path) -> str:
    """Get the tick_hash from the last entry in a file."""
    is_compressed = path.suffix == ".gz"
    last_hash = GENESIS_HASH
    
    try:
        if is_compressed:
            f = gzip.open(path, "rt", encoding="utf-8")
        else:
            f = open(path, "r", encoding="utf-8")

        with f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    last_hash = rec.get("tick_hash", last_hash)
    except Exception:
        pass
    
    return last_hash
