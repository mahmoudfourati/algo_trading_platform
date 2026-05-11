"""
Layer 6 Audit Engine - Hash Chain Implementation

This module implements the core audit entry schema and hash chain logic
for tamper-evident audit logging.
"""

import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Dict


@dataclass
class AuditEntry:
    """
    Audit entry with hash chain linkage.
    
    All 10 required fields for tamper-evident audit logging:
    - entry_id: Unique identifier (UUID string)
    - timestamp_utc: Event timestamp in milliseconds since epoch
    - event_type: Type of audit event (e.g., TICK, SIGNAL, ORDER, ROTATION)
    - source_layer: Layer number 1-6 that generated the event
    - payload: Event-specific data as dictionary
    - trust_score: Trust score from Layer 1 (0.0-1.0)
    - anomaly_score: Anomaly score from Layer 2 (0.0-1.0)
    - system_state: Current system state (e.g., NORMAL, CONSERVATIVE, HALT)
    - previous_hash: SHA-256 hash of previous entry (64 hex chars, or 64 zeros for genesis)
    - current_hash: SHA-256 hash of this entry (64 hex chars)
    """
    entry_id: str  # UUID string
    timestamp_utc: int  # milliseconds since epoch
    event_type: str  # TICK, SIGNAL, ORDER, EXECUTION, ROTATION, etc.
    source_layer: int  # 1-6
    payload: Dict  # Event-specific data
    trust_score: float  # 0.0-1.0
    anomaly_score: float  # 0.0-1.0
    system_state: str  # NORMAL, CONSERVATIVE, HALT
    previous_hash: str  # 64 hex characters (or 64 zeros for genesis)
    current_hash: str  # 64 hex characters


def compute_hash(entry: AuditEntry) -> str:
    """
    Compute SHA-256 hash of an audit entry.
    
    Produces canonical JSON representation:
    - All fields except current_hash are included
    - Keys sorted alphabetically
    - UTF-8 encoded
    - No whitespace (separators=(',', ':'))
    
    Args:
        entry: AuditEntry to hash
        
    Returns:
        64-character hex string (SHA-256 digest)
    """
    # Convert entry to dict, excluding current_hash
    entry_dict = asdict(entry)
    entry_dict.pop('current_hash', None)
    
    # Produce canonical JSON: sorted keys, no whitespace, UTF-8
    canonical_json = json.dumps(entry_dict, sort_keys=True, separators=(',', ':'))
    canonical_bytes = canonical_json.encode('utf-8')
    
    # Compute SHA-256 hash
    hash_digest = hashlib.sha256(canonical_bytes).hexdigest()
    
    return hash_digest


def make_genesis_previous_hash() -> str:
    """
    Generate the genesis previous_hash value.
    
    Returns:
        String of exactly 64 zero characters
    """
    return "0" * 64
