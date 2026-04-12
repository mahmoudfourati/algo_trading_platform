from __future__ import annotations

import json

from services.layer1_hashlog.hash_chain import HashChainLogger, verify_hash_chain


def test_hash_chain_detects_corruption(tmp_path) -> None:
    log_path = tmp_path / "hash_chain.jsonl"

    logger = HashChainLogger(path=log_path)
    logger.start()

    # Append a few entries.
    for i in range(5):
        logger.append(
            symbol="BTC-USDT",
            consensus_mid=100.0 + i,
            trust_score=0.9,
            received_timestamp_ms=1_700_000_000_000 + i,
        )

    logger.stop()

    ok, msg = verify_hash_chain(log_path)
    assert ok, msg

    # Corrupt line 3 by modifying consensus_mid.
    lines = log_path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[2])
    rec["consensus_mid"] = rec["consensus_mid"] + 123.0
    lines[2] = json.dumps(rec, separators=(",", ":"), sort_keys=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok2, msg2 = verify_hash_chain(log_path)
    assert not ok2
    assert "tick_hash mismatch" in msg2
