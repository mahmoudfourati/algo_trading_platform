from services.layer1_ingestion.adapters.binance import BinanceAdapter
from services.layer1_ingestion.adapters.coinbase import CoinbaseAdapter
from services.layer1_ingestion.adapters.kraken import KrakenAdapter


def test_binance_parse_message_combined_wrapper() -> None:
    raw = {
        "stream": "btcusdt@ticker",
        "data": {
            "E": 1710000000123,
            "s": "BTCUSDT",
            "b": "65000.00",
            "a": "65001.00",
            "c": "65000.50",
            "v": "1234.56",
        },
    }
    tick = BinanceAdapter.parse_message(raw, received_timestamp_ms=1710000000999)
    assert tick is not None
    assert tick.exchange_id == "binance"
    assert tick.symbol == "BTC-USDT"
    assert tick.bid == 65000.0
    assert tick.ask == 65001.0
    assert tick.last_price == 65000.5
    assert tick.volume_24h == 1234.56
    assert tick.exchange_timestamp_ms == 1710000000123


def test_coinbase_parse_ticker() -> None:
    raw = {
        "type": "ticker",
        "product_id": "BTC-USDT",
        "best_bid": "65000.00",
        "best_ask": "65001.00",
        "price": "65000.50",
        "volume_24h": "123.45",
        "time": "2026-04-10T00:00:00.123456Z",
        "sequence": 42,
    }
    tick = CoinbaseAdapter.parse_message(raw, received_timestamp_ms=1710000000999)
    assert tick is not None
    assert tick.exchange_id == "coinbase"
    assert tick.symbol == "BTC-USDT"
    assert tick.sequence_id == 42
    assert tick.bid == 65000.0
    assert tick.ask == 65001.0


def test_kraken_parse_ticker_array_message() -> None:
    raw = [
        42,
        {
            "a": ["65001.0", "1", "1.0"],
            "b": ["65000.0", "1", "1.0"],
            "c": ["65000.5", "0.1"],
            "v": ["100", "200"],
        },
        "ticker",
        "XBT/USDT",
    ]
    tick = KrakenAdapter.parse_message(raw, received_timestamp_ms=1710000000999)
    assert tick is not None
    assert tick.exchange_id == "kraken"
    assert tick.symbol == "BTC-USDT"
    assert tick.bid == 65000.0
    assert tick.ask == 65001.0
    assert tick.last_price == 65000.5
    assert tick.volume_24h == 200.0
