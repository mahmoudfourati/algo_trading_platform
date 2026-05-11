"""
Layer 6 Audit Rotation - Log File Rotation Management

This module handles rotation of audit log files when they reach the size limit,
maintaining hash chain continuity across file boundaries.
"""

import logging
import time
from pathlib import Path

from .writer import AuditWriter

logger = logging.getLogger(__name__)


class RotationManager:
    """
    Manages rotation of audit log files at size threshold.
    
    Maintains hash chain continuity by linking the final hash of the old file
    to the first entry of the new file.
    """
    
    def __init__(self, base_path: str, max_size_bytes: int = 100 * 1024 * 1024):
        """
        Initialize the rotation manager.
        
        Args:
            base_path: Base path for audit log files
            max_size_bytes: Maximum file size before rotation (default: 100MB)
        """
        self.base_path = base_path
        self.max_size_bytes = max_size_bytes
        self.current_writer = AuditWriter(base_path)
    
    def check_and_rotate(self, writer: AuditWriter) -> bool:
        """
        Check if rotation is needed and perform it if necessary.
        
        Rotation process:
        1. Check if current file size >= max_size_bytes
        2. If yes:
           a. Write ROTATION event to current file (closing entry)
           b. Capture final hash from current writer
           c. Generate new file path with timestamp
           d. Create new writer with last_hash set to final hash (not genesis)
           e. Write ROTATION event to new file (opening entry)
           f. Update self.current_writer to new writer
        
        Args:
            writer: Current AuditWriter to check
            
        Returns:
            True if rotation occurred, False otherwise
        """
        # Check if rotation is needed
        if writer.file_size_bytes < self.max_size_bytes:
            return False
        
        logger.info(
            f"Rotation triggered: file size {writer.file_size_bytes} bytes "
            f">= threshold {self.max_size_bytes} bytes"
        )
        
        # Step 1: Write ROTATION event to current file (closing entry)
        writer.build_and_write(
            event_type="ROTATION",
            source_layer=6,
            payload={"action": "close", "reason": "size_limit_reached"},
            trust_score=1.0,
            anomaly_score=0.0,
            system_state="NORMAL"
        )
        
        # Step 2: Capture final hash from current writer
        final_hash = writer.last_hash
        
        logger.info(f"Final hash of closing file: {final_hash}")
        
        # Step 3: Generate new file path with timestamp
        base = Path(writer.file_path)
        timestamp = int(time.time() * 1000)  # milliseconds
        new_path = str(base.parent / f"{base.stem}_{timestamp}{base.suffix}")
        
        logger.info(f"Creating new audit log file: {new_path}")
        
        # Step 4: Create new writer with last_hash set to final hash (not genesis)
        new_writer = AuditWriter(new_path)
        new_writer.last_hash = final_hash  # Link to previous file's final hash
        
        # Step 5: Write ROTATION event to new file (opening entry)
        new_writer.build_and_write(
            event_type="ROTATION",
            source_layer=6,
            payload={
                "action": "open",
                "previous_file": writer.file_path,
                "linked_hash": final_hash
            },
            trust_score=1.0,
            anomaly_score=0.0,
            system_state="NORMAL"
        )
        
        # Step 6: Update current_writer to new writer
        self.current_writer = new_writer
        
        logger.info(
            f"Rotation complete: {writer.file_path} -> {new_path}, "
            f"chain linked via hash {final_hash[:16]}..."
        )
        
        return True
