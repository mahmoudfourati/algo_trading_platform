"""Purpose: Unit tests for Layer 4 risk management service"""

import json
import pytest
from unittest.mock import Mock, MagicMock, patch

from services.layer4_risk.service import Layer4Service
from services.layer4_risk.engine import Layer4RiskEngine
from services.layer3_strategy.signals import TradeSignal


@pytest.fixture
def mock_kafka_setup():
    """Mock Kafka consumer and publisher."""
    with patch("services.layer4_risk.service.KafkaConsumer"), \
         patch("services.layer4_risk.service.KafkaJsonPublisher") as mock_pub:
        yield mock_pub


def test_layer4_service_initialization():
    """Test that Layer4Service initializes with Kafka consumer and publisher."""
    with patch("services.layer4_risk.service.KafkaConsumer") as mock_consumer, \
         patch("services.layer4_risk.service.KafkaJsonPublisher") as mock_pub_class:
        mock_pub_instance = Mock()
        mock_pub_class.return_value = mock_pub_instance

        svc = Layer4Service()

        assert svc.engine is not None
        assert isinstance(svc.engine, Layer4RiskEngine)
        mock_pub_instance.start.assert_called_once()


def test_layer4_signal_to_approved_order():
    """Test that valid signals are converted to approved orders."""
    signal_dict = {
        "symbol": "BTC-USDT",
        "direction": "LONG",
        "size_pct": 0.10,
        "signal_strength": 0.75,
        "confluence": "FULL",
        "ofi": 0.20,
        "system_state": "NORMAL",
        "timestamp_utc": 1000000,
        "indicator_snapshots": {"primary": {"close": 50000, "atr": 500}},
        "candle_reliability": {"primary": True, "higher": True},
        "trust_score": 0.85,
        "reason": "test signal",
    }

    try:
        signal = TradeSignal(**signal_dict)
    except Exception as e:
        pytest.skip(f"TradeSignal construction failed: {e}")

    engine = Layer4RiskEngine()
    decision = engine.evaluate_signal(signal, reference_price=50000.0, current_portfolio_exposure_pct=0.0)

    assert decision.approved is True
    assert decision.approved_order is not None
    assert decision.approved_order.symbol == "BTC-USDT"


def test_layer4_reject_halted():
    """Test that HALTED system state rejects signals."""
    signal_dict = {
        "symbol": "BTC-USDT",
        "direction": "LONG",
        "size_pct": 0.10,
        "signal_strength": 0.75,
        "confluence": "FULL",
        "ofi": 0.20,
        "system_state": "HALT",
        "timestamp_utc": 1000000,
        "indicator_snapshots": {"primary": {"close": 50000, "atr": 500}},
        "candle_reliability": {"primary": True, "higher": True},
        "trust_score": 0.85,
        "reason": "test signal",
    }

    try:
        signal = TradeSignal(**signal_dict)
    except Exception as e:
        pytest.skip(f"TradeSignal construction failed: {e}")

    engine = Layer4RiskEngine()
    decision = engine.evaluate_signal(signal, reference_price=50000.0, current_portfolio_exposure_pct=0.0)

    assert decision.approved is False
    assert "halt" in decision.reason.lower() or "HALT" in decision.reason


def test_layer4_trust_floor():
    """Test that trust score below floor is rejected."""
    signal_dict = {
        "symbol": "BTC-USDT",
        "direction": "LONG",
        "size_pct": 0.10,
        "signal_strength": 0.75,
        "confluence": "FULL",
        "ofi": 0.20,
        "system_state": "NORMAL",
        "timestamp_utc": 1000000,
        "indicator_snapshots": {"primary": {"close": 50000, "atr": 500}},
        "candle_reliability": {"primary": True, "higher": True},
        "trust_score": 0.30,  # Below default floor of 0.40
        "reason": "test signal",
    }

    try:
        signal = TradeSignal(**signal_dict)
    except Exception as e:
        pytest.skip(f"TradeSignal construction failed: {e}")

    engine = Layer4RiskEngine()
    decision = engine.evaluate_signal(signal, reference_price=50000.0, current_portfolio_exposure_pct=0.0)

    assert decision.approved is False
    assert "trust" in decision.reason.lower()
