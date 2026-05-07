"""Tests for Layer 1 validated sequence-gap tracking on primary exchange ticks."""

from __future__ import annotations

from services.layer1_validated.service import Layer1ValidatedService


class _Stub:
    def __getattr__(self, _name):
        return None


def _service() -> Layer1ValidatedService:
    return Layer1ValidatedService(
        consumer=_Stub(),
        publisher=_Stub(),
        consensus=_Stub(),
        aligner=_Stub(),
        weights=_Stub(),
        hashlog=_Stub(),
        enabled_exchanges=["binance"],
        primary_exchange="binance",
        liveness=_Stub(),
        _last_sequence_ids={},
        _last_liveness_overdue={},
        _last_liveness_check_s=0.0,
    )


def test_sequence_gap_first_seen_returns_no_penalty_gap() -> None:
    svc = _service()
    gap = svc._compute_sequence_gap(symbol="BTCUSDT", exchange="binance", sequence_id=100)
    assert gap == 1


def test_sequence_gap_detects_positive_gap() -> None:
    svc = _service()
    assert svc._compute_sequence_gap(symbol="BTCUSDT", exchange="binance", sequence_id=100) == 1
    assert svc._compute_sequence_gap(symbol="BTCUSDT", exchange="binance", sequence_id=103) == 3


def test_sequence_gap_non_monotonic_maps_to_max_penalty() -> None:
    svc = _service()
    assert svc._compute_sequence_gap(symbol="BTCUSDT", exchange="binance", sequence_id=100) == 1
    assert svc._compute_sequence_gap(symbol="BTCUSDT", exchange="binance", sequence_id=98) == 10


def test_sequence_gap_missing_sequence_id_returns_none() -> None:
    svc = _service()
    gap = svc._compute_sequence_gap(symbol="BTCUSDT", exchange="binance", sequence_id=None)
    assert gap is None
