#!/usr/bin/env python3
"""Create a dummy HMM model for Layer 2 to start without training data.

This creates a minimal 3-state Gaussian HMM that allows Layer 2 to run.
For production, train a real model using: python -m services.hmm_training.train
"""

import json
import os
from pathlib import Path

def create_dummy_hmm():
    """Create a dummy HMM model file."""
    try:
        from hmmlearn.hmm import GaussianHMM
        import numpy as np
        import joblib
    except ImportError:
        print("ERROR: hmmlearn not installed. Installing...")
        os.system("pip install hmmlearn scikit-learn joblib")
        from hmmlearn.hmm import GaussianHMM
        import numpy as np
        import joblib
    
    # Create artifacts/hmm directory
    hmm_dir = Path("artifacts/hmm")
    hmm_dir.mkdir(parents=True, exist_ok=True)
    
    # Create a simple 3-state Gaussian HMM
    # States: 0=low_vol, 1=normal, 2=high_vol
    model = GaussianHMM(n_components=3, covariance_type="full", n_iter=100)
    
    # Set dummy parameters (these would normally be learned from data)
    # Means for each state (volatility levels)
    model.means_ = np.array([[0.001], [0.005], [0.015]])  # low, normal, high volatility
    
    # Covariances for each state
    model.covars_ = np.array([[[0.0001]], [[0.0005]], [[0.002]]])
    
    # Transition matrix (tendency to stay in same state)
    model.transmat_ = np.array([
        [0.95, 0.04, 0.01],  # low_vol -> low_vol, normal, high_vol
        [0.02, 0.96, 0.02],  # normal -> low_vol, normal, high_vol
        [0.01, 0.04, 0.95],  # high_vol -> low_vol, normal, high_vol
    ])
    
    # Start probabilities (most likely to start in normal state)
    model.startprob_ = np.array([0.2, 0.6, 0.2])
    
    # Save the model
    model_path = hmm_dir / "model.pkl"
    joblib.dump(model, model_path)
    print(f"✅ Created dummy HMM model: {model_path}")
    
    # Create metadata file
    metadata = {
        "model_type": "GaussianHMM",
        "n_states": 3,
        "state_labels": ["low_vol", "normal", "high_vol"],
        "feature": "rv_30m",
        "training_data": "dummy (not trained on real data)",
        "note": "This is a dummy model for testing. Train a real model with: python -m services.hmm_training.train"
    }
    
    metadata_path = hmm_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"✅ Created metadata: {metadata_path}")
    
    print("\n✅ Dummy HMM model created successfully!")
    print("   Layer 2 can now start.")
    print("\n⚠️  For production, train a real model:")
    print("   python -m services.hmm_training.train --days 90 --symbols BTCUSDT,ETHUSDT")

if __name__ == "__main__":
    create_dummy_hmm()
