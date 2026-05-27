"""Offline Isolation Forest training script for Layer 2 anomaly detection.

Trains IF models on historical data with regime-stratified sampling.
"""

import argparse
import logging
import math
import os
import sys
import zipfile
from collections import deque
from pathlib import Path
from typing import Deque, List, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.layer2_anomaly.engine import RollingRV30m, HMMRegimeClassifier

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_binance_vision_data(data_dir: str, symbol: str, days: int = 90) -> pd.DataFrame:
    """Load historical tick data from Binance Vision zip files.
    
    Args:
        data_dir: Path to data/binance_vision directory
        symbol: Trading symbol (e.g., 'BTCUSDT')
        days: Number of days to load
    
    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    logger.info(f"Loading {days} days of {symbol} data from {data_dir}")
    
    data_path = Path(data_dir)
    zip_files = sorted(data_path.glob(f"{symbol}-1m-*.zip"))
    
    if not zip_files:
        raise FileNotFoundError(f"No data files found for {symbol} in {data_dir}")
    
    # Take last N days
    zip_files = zip_files[-days:]
    logger.info(f"Found {len(zip_files)} data files")
    
    dfs = []
    for zip_file in zip_files:
        try:
            with zipfile.ZipFile(zip_file, 'r') as z:
                csv_name = zip_file.stem + '.csv'
                with z.open(csv_name) as f:
                    df = pd.read_csv(f, header=None, names=[
                        'timestamp', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                        'taker_buy_quote', 'ignore'
                    ])
                    dfs.append(df[['timestamp', 'open', 'high', 'low', 'close', 'volume']])
        except Exception as e:
            logger.warning(f"Failed to load {zip_file}: {e}")
            continue
    
    if not dfs:
        raise ValueError(f"No data loaded for {symbol}")
    
    combined = pd.concat(dfs, ignore_index=True)
    logger.info(f"Loaded {len(combined)} candles for {symbol}")
    
    return combined


def compute_features(df: pd.DataFrame, hmm_model_path: str) -> Tuple[np.ndarray, np.ndarray]:
    """Compute features and regime labels from historical data.
    
    Args:
        df: DataFrame with OHLCV data
        hmm_model_path: Path to pre-trained HMM model
    
    Returns:
        Tuple of (features array, regime labels array)
    """
    logger.info("Computing features and regime labels")
    
    # Initialize components
    rv = RollingRV30m()
    hmm = HMMRegimeClassifier(model_path=hmm_model_path, expected_states=2)
    
    features_list = []
    regimes_list = []
    
    prev_price = None
    rolling_volumes = deque(maxlen=300)  # 5-min rolling average
    rolling_spreads = deque(maxlen=300)
    
    for idx, row in df.iterrows():
        timestamp_ms = int(row['timestamp'])
        mid_price = float(row['close'])
        volume = float(row['volume'])
        spread = float(row['high']) - float(row['low'])
        spread_bps = (spread / mid_price * 10000) if mid_price > 0 else 0.0
        
        # Skip first row (need previous price)
        if prev_price is None:
            prev_price = mid_price
            rolling_volumes.append(volume)
            rolling_spreads.append(spread_bps)
            continue
        
        # Compute return
        ret = math.log(mid_price / prev_price) if prev_price > 0 and mid_price > 0 else 0.0
        
        # Update rolling volatility and regime
        rv_30m = rv.add(ts_ms=timestamp_ms, ret=ret)
        regime = hmm.update(rv_30m=rv_30m)
        
        # Compute features (same as online engine)
        price_jump_bps = ((mid_price - prev_price) / prev_price * 10000) if prev_price > 0 else 0.0
        
        # Rolling averages
        volume_avg = sum(rolling_volumes) / len(rolling_volumes) if rolling_volumes else 1.0
        spread_avg = sum(rolling_spreads) / len(rolling_spreads) if rolling_spreads else 10.0
        
        volume_ratio = volume / volume_avg if volume_avg > 0 else 1.0
        spread_ratio = spread_bps / spread_avg if spread_avg > 0 else 1.0
        
        # Time of day features
        tod_s = int((timestamp_ms // 1000) % 86400)
        ang = 2.0 * math.pi * (tod_s / 86400.0)
        tod_sin = math.sin(ang)
        tod_cos = math.cos(ang)
        
        # Feature vector (8 features, matching online engine)
        features = np.array([
            price_jump_bps,
            volume_ratio,
            spread_bps,
            spread_ratio,
            1.0,  # trust_score (assume 1.0 for historical data)
            float(regime.regime),
            tod_sin,
            tod_cos
        ], dtype=float)
        
        features_list.append(features)
        regimes_list.append(regime.regime)
        
        # Update state
        prev_price = mid_price
        rolling_volumes.append(volume)
        rolling_spreads.append(spread_bps)
        
        # Progress logging
        if (idx + 1) % 10000 == 0:
            logger.info(f"Processed {idx + 1}/{len(df)} candles")
    
    features_array = np.stack(features_list, axis=0)
    regimes_array = np.array(regimes_list, dtype=int)
    
    logger.info(f"Computed {len(features_array)} feature vectors")
    logger.info(f"Regime distribution: {np.bincount(regimes_array)}")
    
    return features_array, regimes_array


def stratified_sample(features: np.ndarray, regimes: np.ndarray, 
                      samples_per_regime: int = 50000) -> np.ndarray:
    """Sample equally from each regime to avoid bias.
    
    Args:
        features: Feature array (N, 8)
        regimes: Regime labels (N,)
        samples_per_regime: Number of samples to take from each regime
    
    Returns:
        Balanced feature array
    """
    logger.info(f"Stratified sampling: {samples_per_regime} samples per regime")
    
    unique_regimes = np.unique(regimes)
    sampled_features = []
    
    for regime in unique_regimes:
        regime_mask = regimes == regime
        regime_features = features[regime_mask]
        
        n_available = len(regime_features)
        n_sample = min(samples_per_regime, n_available)
        
        # Random sample without replacement
        indices = np.random.choice(n_available, size=n_sample, replace=False)
        sampled = regime_features[indices]
        sampled_features.append(sampled)
        
        logger.info(f"Regime {regime}: sampled {n_sample}/{n_available} samples")
    
    balanced = np.vstack(sampled_features)
    logger.info(f"Total balanced samples: {len(balanced)}")
    
    return balanced


def train_isolation_forest(features: np.ndarray, 
                           n_estimators: int = 100,
                           contamination: float = 0.05,
                           max_samples: int = 256,
                           seed: int = 42) -> IsolationForest:
    """Train Isolation Forest model.
    
    Args:
        features: Feature array (N, 8)
        n_estimators: Number of trees
        contamination: Expected proportion of anomalies
        max_samples: Samples per tree
        seed: Random seed
    
    Returns:
        Trained IsolationForest model
    """
    logger.info(f"Training Isolation Forest: n_estimators={n_estimators}, "
                f"contamination={contamination}, max_samples={max_samples}")
    
    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        max_samples=max_samples,
        random_state=seed,
        n_jobs=-1  # Use all CPU cores
    )
    
    model.fit(features)
    
    # Validate model
    test_scores = model.decision_function(features[:100])
    logger.info(f"Model trained successfully. Test scores range: "
                f"[{test_scores.min():.4f}, {test_scores.max():.4f}]")
    
    return model


def main():
    parser = argparse.ArgumentParser(description='Train Isolation Forest models offline')
    parser.add_argument('--data-dir', type=str, 
                       default='data/binance_vision',
                       help='Path to Binance Vision data directory')
    parser.add_argument('--hmm-model', type=str,
                       default='artifacts/hmm/model.pkl',
                       help='Path to pre-trained HMM model')
    parser.add_argument('--output-dir', type=str,
                       default='artifacts/if_models',
                       help='Output directory for trained models')
    parser.add_argument('--symbols', type=str, nargs='+',
                       default=['BTCUSDT', 'ETHUSDT'],
                       help='Symbols to train models for')
    parser.add_argument('--days', type=int, default=90,
                       help='Number of days of historical data')
    parser.add_argument('--samples-per-regime', type=int, default=50000,
                       help='Samples per regime for stratified sampling')
    parser.add_argument('--seed', type=int, default=42,
                       help='Random seed')
    
    args = parser.parse_args()
    
    # Set random seed
    np.random.seed(args.seed)
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Check HMM model exists
    if not Path(args.hmm_model).exists():
        logger.error(f"HMM model not found: {args.hmm_model}")
        sys.exit(1)
    
    # Train model for each symbol
    for symbol in args.symbols:
        logger.info(f"\n{'='*60}")
        logger.info(f"Training IF model for {symbol}")
        logger.info(f"{'='*60}\n")
        
        try:
            # Load data
            df = load_binance_vision_data(args.data_dir, symbol, args.days)
            
            # Compute features and regimes
            features, regimes = compute_features(df, args.hmm_model)
            
            # Stratified sampling
            balanced_features = stratified_sample(features, regimes, args.samples_per_regime)
            
            # Train model
            model = train_isolation_forest(balanced_features, seed=args.seed)
            
            # Save model
            model_path = output_dir / f"{symbol}_if.pkl"
            joblib.dump(model, model_path)
            logger.info(f"Model saved to {model_path}")
            
            # Save metadata
            metadata = {
                'symbol': symbol,
                'training_date': pd.Timestamp.now().isoformat(),
                'days': args.days,
                'n_samples': len(balanced_features),
                'n_features': balanced_features.shape[1],
                'regime_distribution': np.bincount(regimes).tolist(),
                'seed': args.seed
            }
            metadata_path = output_dir / f"{symbol}_if_metadata.json"
            import json
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            logger.info(f"Metadata saved to {metadata_path}")
            
        except Exception as e:
            logger.error(f"Failed to train model for {symbol}: {e}", exc_info=True)
            continue
    
    logger.info("\n" + "="*60)
    logger.info("Training complete!")
    logger.info("="*60)


if __name__ == '__main__':
    main()
