"""Layer 3 feature flags for runtime configurability."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Layer3FeatureFlags:
    """Runtime feature toggles for Layer 3 strategy behavior."""

    enable_ofi_gate: bool = True
    enable_higher_timeframe_confirmation: bool = True
    enable_candle_reliability_gate: bool = True


def load_layer3_feature_flags() -> Layer3FeatureFlags:
    """Load feature flags from environment or config."""

    path = os.getenv("LAYER3_FEATURE_FLAGS_PATH")
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Layer3FeatureFlags(**{k: v for k, v in data.items() if k in Layer3FeatureFlags.__dataclass_fields__})
    return Layer3FeatureFlags()
