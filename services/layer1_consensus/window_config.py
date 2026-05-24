"""Consensus window configuration loader.

Loads per-symbol alignment window configuration from YAML file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

import yaml
from pydantic import BaseModel, Field


class ConsensusWindowConfig(BaseModel):
    """Consensus window configuration."""
    
    default_window_ms: int = Field(default=50, description="Default window for all symbols")
    symbol_overrides: Dict[str, int] = Field(default_factory=dict, description="Per-symbol window overrides")
    
    def get_window_ms(self, symbol: str) -> int:
        """Get alignment window for a symbol.
        
        Args:
            symbol: Symbol name (e.g., "BTC-USDT")
            
        Returns:
            Window size in milliseconds
        """
        return self.symbol_overrides.get(symbol, self.default_window_ms)


def load_window_config(path: Optional[str] = None) -> ConsensusWindowConfig:
    """Load consensus window configuration from YAML file.
    
    Args:
        path: Path to config file. Defaults to config/consensus_windows.yaml
        
    Returns:
        ConsensusWindowConfig instance
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    if path is None:
        path = os.getenv("CONSENSUS_WINDOW_CONFIG", "config/consensus_windows.yaml")
    
    config_path = Path(path)
    
    if not config_path.exists():
        # Return default config if file doesn't exist
        return ConsensusWindowConfig()
    
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    if data is None:
        return ConsensusWindowConfig()
    
    # Handle None values in YAML
    if data.get("symbol_overrides") is None:
        data["symbol_overrides"] = {}
    
    return ConsensusWindowConfig.model_validate(data)


def get_window_ms_from_env(symbol: str, default: int = 50) -> int:
    """Get window size from environment variable (legacy support).
    
    Checks for CONSENSUS_WINDOW_MS_<SYMBOL> environment variable.
    Falls back to CONSENSUS_WINDOW_MS or default.
    
    Args:
        symbol: Symbol name (e.g., "BTC-USDT")
        default: Default window size if not configured
        
    Returns:
        Window size in milliseconds
    """
    # Try symbol-specific env var (replace - with _)
    symbol_env = f"CONSENSUS_WINDOW_MS_{symbol.replace('-', '_')}"
    if symbol_env in os.environ:
        return int(os.environ[symbol_env])
    
    # Try global env var
    if "CONSENSUS_WINDOW_MS" in os.environ:
        return int(os.environ["CONSENSUS_WINDOW_MS"])
    
    return default
