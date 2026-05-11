"""
Layer 6 Audit Writer - File Writing and Hash Chain Management

This module handles writing audit entries to disk and maintaining
the hash chain state.
"""

import json
import os
import time
import uuid
from dataclasses import asdict
from typing import Dict

from .engine import AuditEntry, compute_hash, make_genesis_previous_hash


class AuditWriter:
    """
    Writes audit entries to a file with hash chain linkage.
    
    Maintains the hash chain by tracking the last written entry's hash
    and using it as the previous_hash for the next entry.
    """
    
    def __init__(self, file_path: str):
        """
        Initialize the audit writer.
        
        Args:
            file_path: Path to the audit log file
        """
        self.file_path = file_path
        self.last_hash = make_genesis_previous_hash()
        self.writes_halted = False
    
    def write_entry(self, entry: AuditEntry) -> None:
        """
        Write an audit entry to the file as a single line of JSON.
        
        Args:
            entry: AuditEntry to write
        """
        # Convert entry to dict
        entry_dict = asdict(entry)
        
        # Serialize to JSON (single line, no pretty-printing)
        json_line = json.dumps(entry_dict, separators=(',', ':'))
        
        # Append to file with newline
        with open(self.file_path, 'a', encoding='utf-8') as f:
            f.write(json_line + '\n')
    
    def build_and_write(
        self,
        event_type: str,
        source_layer: int,
        payload: Dict,
        trust_score: float,
        anomaly_score: float,
        system_state: str
    ) -> AuditEntry:
        """
        Build a new audit entry, compute its hash, write it, and update state.
        
        Args:
            event_type: Type of audit event
            source_layer: Layer number 1-6
            payload: Event-specific data
            trust_score: Trust score 0.0-1.0
            anomaly_score: Anomaly score 0.0-1.0
            system_state: System state (NORMAL, CONSERVATIVE, HALT)
            
        Returns:
            The created and written AuditEntry
        """
        # Generate UUID for this entry
        entry_id = str(uuid.uuid4())
        
        # Get current timestamp in milliseconds
        timestamp_utc = int(time.time() * 1000)
        
        # Create entry with previous_hash from last_hash
        entry = AuditEntry(
            entry_id=entry_id,
            timestamp_utc=timestamp_utc,
            event_type=event_type,
            source_layer=source_layer,
            payload=payload,
            trust_score=trust_score,
            anomaly_score=anomaly_score,
            system_state=system_state,
            previous_hash=self.last_hash,
            current_hash=""  # Will be computed next
        )
        
        # Compute hash for this entry
        entry.current_hash = compute_hash(entry)
        
        # Write to file
        self.write_entry(entry)
        
        # Update last_hash for next entry
        self.last_hash = entry.current_hash
        
        return entry
    
    @property
    def file_size_bytes(self) -> int:
        """
        Get the current size of the audit log file in bytes.
        
        Returns:
            File size in bytes, or 0 if file doesn't exist
        """
        if os.path.exists(self.file_path):
            return os.path.getsize(self.file_path)
        return 0
