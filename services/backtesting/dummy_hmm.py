"""A small dummy HMM class placed in services.backtesting so joblib loads.

This makes pickled DummyHMM instances importable by the backtest loader.
"""

from __future__ import annotations

import numpy as np


class DummyHMM:
    def predict(self, X):
        n = X.shape[0]
        return np.zeros(n, dtype=int)

    def predict_proba(self, X):
        n = X.shape[0]
        out = np.zeros((n, 2), dtype=float)
        out[:, 0] = 0.5
        out[:, 1] = 0.5
        return out
