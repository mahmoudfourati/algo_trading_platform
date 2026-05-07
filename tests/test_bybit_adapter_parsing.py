"""Tests for Bybit adapter message parsing.

Covers snapshot + delta merge behavior for the v5 linear tickers stream.
"""

from services.layer1_ingestion.adapters.bybit import BybitAdapter


def test_bybit_stateful_parse_merges_delta() -> None:
    ad = BybitAdapter(["BTC-USDT"])

    snapshot = {
        "topic": "tickers.BTCUSDT",
        "type": "snapshot",
        "ts": 1234567890,
        "data": {
            "symbol": "BTCUSDT",
            "lastPrice": "100.0",
            "bid1Price": "99.5",
            "ask1Price": "100.5",
            "turnover24h": "1000.0",
        },
    }

    t1 = ad._parse_message_with_state(snapshot, received_timestamp_ms=111)
    assert t1 is not None
    assert t1.exchange_id == "bybit"
    assert t1.symbol == "BTC-USDT"
    assert t1.last_price == 100.0
    assert t1.bid == 99.5
    assert t1.ask == 100.5

    delta = {
        "topic": "tickers.BTCUSDT",
        "type": "delta",
        "ts": 1234567999,
        "data": {
            "symbol": "BTCUSDT",
            "bid1Price": "98.0",
        },
    }

    t2 = ad._parse_message_with_state(delta, received_timestamp_ms=222)
    assert t2 is not None
    assert t2.last_price == 100.0
    assert t2.bid == 98.0
    assert t2.ask == 100.5
    assert t2.exchange_timestamp_ms == 1234567999
