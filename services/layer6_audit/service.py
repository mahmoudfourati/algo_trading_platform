# TAMPER-EVIDENCE LIMITATION
#
# This audit log is tamper-evident, not tamper-proof.
#
# A single-writer hash chain can be recomputed by an attacker with write access
# to the log file — modifying any entry and recomputing all subsequent hashes
# produces a chain that passes integrity verification.
#
# This is a known and accepted limitation. The log provides mathematical proof
# of integrity only under the assumption that the operator controls file system access.
#
# For true tamper-proof logging, a distributed consensus mechanism (e.g. blockchain)
# would be required. That complexity is not justified for this project's threat model.

"""
Layer 6 Audit Service

Consumes audit events from Kafka, writes them to a tamper-evident hash chain log,
performs periodic integrity verification, and handles log rotation.
"""

import json
import logging
import os
import time

from kafka import KafkaConsumer
from prometheus_client import Counter, Gauge, Histogram

from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.service_health import mark_service_healthy

from .rotation import RotationManager
from .verifier import AuditVerifier

logger = logging.getLogger(__name__)


# === PROMETHEUS METRICS ===

# Throughput
_events_in_total = Counter("layer6_events_in_total", "Audit events consumed.")
_bad_in_total = Counter("layer6_bad_in_total", "Events that failed validation.")
_events_written_total = Counter("layer6_events_written_total", "Events written to audit log.")

# Integrity
_hash_verification_failures = Counter("audit_hash_verification_failures_total", "Hash chain verification failures.", ["reason"])
_chain_continuity_breaks = Counter("audit_chain_continuity_breaks_total", "Hash chain continuity breaks detected.")
_chain_length = Gauge("audit_chain_length", "Current hash chain length (total events).")

# Performance
_audit_log_write_latency_ms = Histogram(
    "audit_log_write_latency_ms",
    "Audit log write latency in milliseconds.",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 50, 100]
)
_log_rotation_events = Counter("audit_log_rotation_events_total", "Log rotation events.")
_log_file_size_bytes = Gauge("audit_log_file_size_bytes", "Current audit log file size in bytes.")


def main() -> None:
    """
    Main entry point for Layer 6 Audit Service.
    
    Consumes audit events from Kafka audit.events topic, writes them to a
    tamper-evident hash chain log with automatic rotation and integrity verification.
    """
    # Start metrics HTTP server
    metrics_port = int(os.getenv("METRICS_PORT", "9107"))
    start_metrics_http_server(port=metrics_port)
    
    # Mark service as healthy
    mark_service_healthy("layer6_audit", "layer6")
    
    # Configuration
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
    audit_topic = os.getenv("KAFKA_AUDIT_TOPIC", "audit.events")
    group_id = os.getenv("KAFKA_GROUP_ID", f"layer6-audit-{int(time.time())}")
    log_base_path = os.getenv("AUDIT_LOG_PATH", "logs/audit_chain.jsonl")
    max_file_size = int(os.getenv("AUDIT_MAX_FILE_SIZE_BYTES", str(100 * 1024 * 1024)))  # 100MB default
    
    logger.info(
        f"Starting Layer 6 Audit Service: topic={audit_topic}, "
        f"log_path={log_base_path}, max_size={max_file_size} bytes"
    )
    
    # Initialize Kafka consumer
    consumer = KafkaConsumer(
        audit_topic,
        bootstrap_servers=bootstrap,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest"),
    )
    
    # Initialize rotation manager (creates initial writer)
    rotation_manager = RotationManager(
        base_path=log_base_path,
        max_size_bytes=max_file_size
    )
    
    # Initialize verifier
    verifier = AuditVerifier()
    
    # Define chain break callback
    def on_chain_break(entry_id: str) -> None:
        """Called when hash chain integrity verification fails."""
        logger.critical(f"Hash chain break detected at entry {entry_id}")
        _chain_continuity_breaks.inc()
        _hash_verification_failures.labels(reason="chain_break").inc()
        emit_audit_event(
            "layer6.chain_break",
            source="layer6_audit",
            payload={
                "broken_entry_id": entry_id,
                "severity": "CRITICAL",
                "action": "writes_halted"
            }
        )
    
    # Start background verification (60-second interval)
    verifier.start_background_verification(
        file_path=log_base_path,
        writer=rotation_manager.current_writer,
        on_break=on_chain_break
    )
    
    # Emit startup audit event
    emit_audit_event(
        "layer6.start",
        source="layer6_audit",
        payload={
            "audit_topic": audit_topic,
            "log_path": log_base_path,
            "max_file_size_bytes": max_file_size
        }
    )
    
    logger.info("Layer 6 Audit Service started, consuming from Kafka...")
    
    # Track chain length
    chain_entry_count = 0
    
    try:
        # Main consumption loop
        while True:
            records = consumer.poll(timeout_ms=1000, max_records=100)
            
            if not records:
                continue
            
            for _tp, messages in records.items():
                for msg in messages:
                    _events_in_total.inc()
                    
                    try:
                        # Parse Kafka message
                        raw = json.loads(msg.value.decode("utf-8"))
                        
                        # Extract fields from audit event
                        event_type = raw.get("event_type", "UNKNOWN")
                        source = raw.get("source", "unknown")
                        timestamp_utc = raw.get("timestamp_ms", int(time.time() * 1000))
                        payload = raw.get("payload", {})
                        
                        # Determine source layer from source string
                        # Format: "layer1_*", "layer2_*", etc.
                        source_layer = 6  # Default to Layer 6
                        if source.startswith("layer"):
                            try:
                                source_layer = int(source[5])  # Extract digit after "layer"
                            except (ValueError, IndexError):
                                pass
                        
                        # Extract trust_score and anomaly_score from payload if available
                        trust_score = float(payload.get("trust_score", 1.0))
                        anomaly_score = float(payload.get("anomaly_score", 0.0))
                        system_state = payload.get("system_state", "NORMAL")
                        
                        # Check if writes are halted
                        if rotation_manager.current_writer.writes_halted:
                            logger.warning(
                                f"Skipping audit entry write (writes halted): {event_type}"
                            )
                            continue
                        
                        # Write audit entry to hash chain with timing
                        write_start = time.perf_counter()
                        rotation_manager.current_writer.build_and_write(
                            event_type=event_type,
                            source_layer=source_layer,
                            payload=payload,
                            trust_score=trust_score,
                            anomaly_score=anomaly_score,
                            system_state=system_state
                        )
                        write_ms = (time.perf_counter() - write_start) * 1000
                        _audit_log_write_latency_ms.observe(write_ms)
                        _events_written_total.inc()
                        
                        # Update chain length and file size
                        chain_entry_count += 1
                        _chain_length.set(chain_entry_count)
                        _log_file_size_bytes.set(rotation_manager.current_writer.file_size_bytes)
                        
                        # Check for rotation after each write
                        # CRITICAL: Always use rotation_manager.current_writer, not a cached reference
                        rotated = rotation_manager.check_and_rotate(rotation_manager.current_writer)
                        
                        if rotated:
                            _log_rotation_events.inc()
                            logger.info("Log rotation completed, continuing with new file")
                        
                    except json.JSONDecodeError as e:
                        _bad_in_total.inc()
                        logger.error(f"Failed to decode Kafka message: {e}")
                        emit_audit_event(
                            "layer6.bad_message",
                            source="layer6_audit",
                            payload={"error": repr(e)}
                        )
                    except Exception as e:
                        _bad_in_total.inc()
                        logger.error(f"Error processing audit event: {e}")
                        emit_audit_event(
                            "layer6.processing_error",
                            source="layer6_audit",
                            payload={"error": repr(e)}
                        )
    
    except KeyboardInterrupt:
        logger.info("Shutting down Layer 6 Audit Service...")
    finally:
        consumer.close()
        emit_audit_event(
            "layer6.stop",
            source="layer6_audit",
            payload={"reason": "shutdown"}
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    main()
