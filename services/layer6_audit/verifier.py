"""
Layer 6 Audit Verifier - Hash Chain Integrity Verification

This module handles verification of the audit log hash chain integrity.
"""

import json
import logging
import os
import threading
import time
from typing import Callable, Optional, Tuple

from .engine import AuditEntry, compute_hash
from .writer import AuditWriter

logger = logging.getLogger(__name__)


class AuditVerifier:
    """
    Verifies the integrity of the audit log hash chain.
    
    Provides both on-demand verification and background periodic verification.
    """
    
    def verify_chain(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """
        Verify the entire hash chain from genesis to the latest entry.
        
        Reads every line from the file, recomputes hashes, and verifies:
        1. Each entry's current_hash matches the recomputed hash
        2. Each entry's previous_hash matches the previous entry's current_hash
        
        Args:
            file_path: Path to the audit log file
            
        Returns:
            Tuple of (is_valid, broken_entry_id):
            - (True, None) if chain is intact
            - (False, entry_id) if chain is broken at entry_id
        """
        if not os.path.exists(file_path):
            # Empty chain is valid
            return (True, None)
        
        previous_hash = None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    # Parse JSON line
                    entry_dict = json.loads(line)
                    
                    # Reconstruct AuditEntry
                    entry = AuditEntry(**entry_dict)
                    
                    # Recompute hash (compute_hash excludes current_hash)
                    recomputed_hash = compute_hash(entry)
                    
                    # Verify current_hash matches recomputed hash
                    if entry.current_hash != recomputed_hash:
                        logger.error(
                            f"Hash mismatch at line {line_num}, entry {entry.entry_id}: "
                            f"stored={entry.current_hash}, recomputed={recomputed_hash}"
                        )
                        return (False, entry.entry_id)
                    
                    # Verify previous_hash linkage (skip for first entry)
                    if previous_hash is not None:
                        if entry.previous_hash != previous_hash:
                            logger.error(
                                f"Chain break at line {line_num}, entry {entry.entry_id}: "
                                f"previous_hash={entry.previous_hash}, expected={previous_hash}"
                            )
                            return (False, entry.entry_id)
                    
                    # Update previous_hash for next iteration
                    previous_hash = entry.current_hash
                    
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error at line {line_num}: {e}")
                    return (False, f"line_{line_num}")
                except Exception as e:
                    logger.error(f"Verification error at line {line_num}: {e}")
                    return (False, f"line_{line_num}")
        
        # All entries verified successfully
        return (True, None)
    
    def start_background_verification(
        self,
        file_path: str,
        writer: AuditWriter,
        on_break: Callable[[str], None]
    ) -> None:
        """
        Start background verification thread that runs every 60 seconds.
        
        On chain break:
        - Calls on_break(entry_id) callback
        - Sets writer.writes_halted = True to stop new writes
        
        Args:
            file_path: Path to the audit log file
            writer: AuditWriter instance to halt on break
            on_break: Callback function called with entry_id on chain break
        """
        def verification_loop():
            """Background verification loop."""
            while True:
                time.sleep(60)  # Wait 60 seconds between checks
                
                logger.debug("Running background hash chain verification")
                is_valid, broken_entry_id = self.verify_chain(file_path)
                
                if not is_valid:
                    logger.critical(
                        f"HASH CHAIN BREAK DETECTED at entry {broken_entry_id}. "
                        "Halting new writes."
                    )
                    
                    # Halt writes
                    writer.writes_halted = True
                    
                    # Call break callback
                    on_break(broken_entry_id)
                    
                    # Stop verification loop after first break
                    break
                else:
                    logger.debug("Hash chain verification passed")
        
        # Start daemon thread (won't block process shutdown)
        verification_thread = threading.Thread(
            target=verification_loop,
            daemon=True,
            name="AuditVerifier"
        )
        verification_thread.start()
        
        logger.info("Background hash chain verification started (60s interval)")
