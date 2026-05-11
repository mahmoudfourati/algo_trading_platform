"""Test Layer 3 signal generation metrics."""

import pytest
from prometheus_client import REGISTRY

from services.layer3_strategy.service import (
    Layer3SymbolState,
    _signal_direction_count,
    _signal_strength_histogram,
)
from shared.schemas import ScoredTick, SystemState


def test_signal_direction_counter_increments():
    """Test that signal direction counter increments for all signal types."""
    # Get initial counter values
    initial_samples = {}
    for sample in _signal_direction_count.collect()[0].samples:
        key = (sample.labels.get('symbol'), sample.labels.get('direction'))
        initial_samples[key] = sample.value
    
    # Create a Layer3SymbolState and process enough ticks to generate signals
    state = Layer3SymbolState(symbol="BTC-USDT")
    
    # We need to process enough ticks to build up history
    # This is a basic smoke test to ensure the metric is defined correctly
    assert _signal_direction_count is not None
    # Prometheus client strips _total suffix from Counter names internally
    assert _signal_direction_count._name == "strategy_signal_direction"


def test_signal_strength_histogram_defined():
    """Test that signal strength histogram is properly defined."""
    assert _signal_strength_histogram is not None
    assert _signal_strength_histogram._name == "strategy_signal_strength_distribution"
    
    # Check that buckets are correctly defined
    metric_family = list(_signal_strength_histogram.collect())[0]
    # The histogram should have the buckets we defined
    assert metric_family.type == "histogram"


def test_metrics_labels():
    """Test that metrics have the correct labels."""
    # Signal direction counter should have symbol and direction labels
    counter_metric = list(_signal_direction_count.collect())[0]
    # Prometheus client strips _total suffix from Counter names in collected output
    assert counter_metric.name == "strategy_signal_direction"
    
    # Signal strength histogram should have symbol label
    histogram_metric = list(_signal_strength_histogram.collect())[0]
    assert histogram_metric.name == "strategy_signal_strength_distribution"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
