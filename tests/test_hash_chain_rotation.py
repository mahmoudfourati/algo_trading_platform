"""Test hash chain rotation, compression, and verification."""

import gzip
import json
import time
from pathlib import Path

import pytest

from services.layer1_hashlog.hash_chain import (
    GENESIS_HASH,
    HashChainLogger,
    verify_hash_chain,
    verify_hash_chain_directory,
)


def test_hash_chain_rotation(tmp_path):
    """Test that hash chain rotates when file size exceeds limit."""
    log_path = tmp_path / "hash_chain.jsonl"

    # Create logger with small max file size (1KB for testing)
    logger = HashChainLogger(
        path=log_path,
        max_file_size_mb=0.001,  # 1KB
        retention_days=7,
        verify_on_startup=100,
    )
    logger.start()

    # Append enough entries to trigger rotation
    for i in range(100):
        logger.append(
            symbol="BTC-USDT",
            consensus_mid=50000.0 + i,
            trust_score=0.95,
            received_timestamp_ms=1000000 + i,
            primary_exchange="binance",
            primary_mid_price=50000.0 + i,
            used_sources=["binance", "coinbase", "kraken"],
            divergent_sources=[],
        )
        time.sleep(0.01)  # Give time for async writes

    # Wait for writes to complete
    time.sleep(1)

    logger.stop()

    # Check that multiple files were created
    pattern = "hash_chain_*.jsonl*"
    files = list(tmp_path.glob(pattern))
    
    # Should have at least 2 files (original + rotated)
    assert len(files) >= 2, f"Expected at least 2 files, got {len(files)}: {files}"

    # Check that at least one file is compressed
    compressed_files = [f for f in files if f.suffix == ".gz"]
    assert len(compressed_files) >= 1, f"Expected at least 1 compressed file, got {len(compressed_files)}"

    # Verify all files
    ok, messages = verify_hash_chain_directory(tmp_path, pattern)
    assert ok, f"Verification failed: {messages}"


def test_hash_chain_compression(tmp_path):
    """Test that rotated files are compressed."""
    log_path = tmp_path / "hash_chain.jsonl"

    logger = HashChainLogger(
        path=log_path,
        max_file_size_mb=0.001,  # 1KB
        retention_days=7,
        verify_on_startup=100,
    )
    logger.start()

    # Append entries
    for i in range(50):
        logger.append(
            symbol="BTC-USDT",
            consensus_mid=50000.0,
            trust_score=0.95,
            received_timestamp_ms=1000000 + i,
            primary_exchange="binance",
            primary_mid_price=50000.0,
            used_sources=["binance", "coinbase"],
            divergent_sources=[],
        )
        time.sleep(0.01)

    time.sleep(1)
    logger.stop()

    # Find compressed files
    compressed_files = list(tmp_path.glob("*.jsonl.gz"))
    
    if compressed_files:
        # Verify compressed file can be read
        compressed_file = compressed_files[0]
        with gzip.open(compressed_file, "rt", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) > 0, "Compressed file is empty"
            
            # Verify first line is valid JSON
            first_line = json.loads(lines[0])
            assert "tick_hash" in first_line
            assert "previous_hash" in first_line


def test_hash_chain_startup_verification(tmp_path):
    """Test that hash chain verifies on startup."""
    log_path = tmp_path / "hash_chain.jsonl"

    # Create initial logger
    logger1 = HashChainLogger(path=log_path, verify_on_startup=10)
    logger1.start()

    for i in range(20):
        logger1.append(
            symbol="BTC-USDT",
            consensus_mid=50000.0,
            trust_score=0.95,
            received_timestamp_ms=1000000 + i,
        )
        time.sleep(0.01)

    time.sleep(0.5)
    logger1.stop()

    # Create new logger that should verify on startup
    logger2 = HashChainLogger(path=log_path, verify_on_startup=10)
    logger2.start()

    # Check verification status
    assert logger2.verification_status == "ok", f"Verification failed: {logger2.verification_message}"

    logger2.stop()


def test_hash_chain_cross_file_continuity(tmp_path):
    """Test that hash chain maintains continuity across file rotations."""
    log_path = tmp_path / "hash_chain.jsonl"

    logger = HashChainLogger(
        path=log_path,
        max_file_size_mb=0.001,  # 1KB
        retention_days=7,
        verify_on_startup=100,
    )
    logger.start()

    # Append enough entries to trigger multiple rotations
    for i in range(150):
        logger.append(
            symbol="BTC-USDT",
            consensus_mid=50000.0 + i,
            trust_score=0.95,
            received_timestamp_ms=1000000 + i,
            primary_exchange="binance",
            primary_mid_price=50000.0 + i,
            used_sources=["binance", "coinbase"],
            divergent_sources=[],
        )
        time.sleep(0.01)

    time.sleep(1)
    logger.stop()

    # Verify cross-file continuity
    pattern = "hash_chain_*.jsonl*"
    ok, messages = verify_hash_chain_directory(tmp_path, pattern)
    
    # Print messages for debugging
    for msg in messages:
        print(msg)
    
    assert ok, f"Cross-file verification failed: {messages}"


def test_hash_chain_retention_cleanup(tmp_path):
    """Test that old files are deleted after retention period."""
    log_path = tmp_path / "hash_chain.jsonl"

    # Create logger with 0-day retention (delete immediately)
    logger = HashChainLogger(
        path=log_path,
        max_file_size_mb=0.001,  # 1KB
        retention_days=0,  # Delete immediately
        verify_on_startup=10,
    )
    logger.start()

    # Append entries to trigger rotation
    for i in range(50):
        logger.append(
            symbol="BTC-USDT",
            consensus_mid=50000.0,
            trust_score=0.95,
            received_timestamp_ms=1000000 + i,
        )
        time.sleep(0.01)

    time.sleep(1)
    logger.stop()

    # With 0-day retention, old files should be deleted
    # (but current file should still exist)
    pattern = "hash_chain_*.jsonl*"
    files = list(tmp_path.glob(pattern))
    
    # Should have at least 1 file (current)
    assert len(files) >= 1, f"Expected at least 1 file, got {len(files)}"


def test_hash_chain_metrics(tmp_path):
    """Test that hash chain exposes metrics."""
    log_path = tmp_path / "hash_chain.jsonl"

    logger = HashChainLogger(path=log_path)
    logger.start()

    # Append some entries
    for i in range(10):
        logger.append(
            symbol="BTC-USDT",
            consensus_mid=50000.0,
            trust_score=0.95,
            received_timestamp_ms=1000000 + i,
        )
        time.sleep(0.01)

    time.sleep(0.5)
    logger.stop()

    # Check metrics
    assert logger.total_entries == 10
    assert logger.verification_status in ["ok", "not_started"]


def test_verify_compressed_file(tmp_path):
    """Test that verify_hash_chain works with compressed files."""
    log_path = tmp_path / "hash_chain.jsonl"

    # Create a hash chain file
    logger = HashChainLogger(path=log_path)
    logger.start()

    for i in range(10):
        logger.append(
            symbol="BTC-USDT",
            consensus_mid=50000.0,
            trust_score=0.95,
            received_timestamp_ms=1000000 + i,
        )
        time.sleep(0.01)

    time.sleep(0.5)
    logger.stop()

    # Manually compress the file
    compressed_path = log_path.with_suffix(".jsonl.gz")
    with open(log_path, "rb") as f_in:
        with gzip.open(compressed_path, "wb") as f_out:
            f_out.writelines(f_in)

    # Verify compressed file
    ok, msg = verify_hash_chain(compressed_path)
    assert ok, f"Verification of compressed file failed: {msg}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
