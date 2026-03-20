"""ML configuration: symbols, timeframes, paths, hyperparameters."""
from dataclasses import dataclass, field
from pathlib import Path

# Paths
ML_DATA_DIR = Path(__file__).parent.parent.parent / "ml_data"
RAW_DIR = ML_DATA_DIR / "raw"
PROCESSED_DIR = ML_DATA_DIR / "processed"
MODELS_DIR = ML_DATA_DIR / "models"

# Symbols to download and train on
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

# Timeframes
PRIMARY_TIMEFRAME = "1h"
SUPPORT_TIMEFRAMES = ["4h", "1d"]

# Historical data range
DOWNLOAD_START = "2020-01-01"


@dataclass
class LabelConfig:
    """Triple Barrier Labeling parameters."""
    tp_pct: float = 0.02          # Take Profit: +2%
    sl_pct: float = 0.01          # Stop Loss: -1%
    horizon_bars: int = 12        # Max lookahead: 12 bars (12h for 1h timeframe)
    min_samples_per_class: int = 100


@dataclass
class FeatureConfig:
    """Feature engineering parameters."""
    rsi_periods: list[int] = field(default_factory=lambda: [7, 14])
    sma_fast: int = 9
    sma_slow: int = 21
    ema_fast: int = 12
    ema_slow: int = 26
    atr_period: int = 14
    bb_period: int = 20
    adx_period: int = 14
    volume_ma_period: int = 20
    obv_slope_period: int = 10
    rolling_std_period: int = 20
    normalization_window: int = 90  # Rolling window for normalization


@dataclass
class XGBoostConfig:
    """XGBoost hyperparameters (anti-overfitting)."""
    objective: str = "binary:logistic"
    eval_metric: str = "logloss"
    max_depth: int = 4
    min_child_weight: int = 5
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    learning_rate: float = 0.05
    n_estimators: int = 500
    reg_alpha: float = 0.1
    reg_lambda: float = 1.0
    early_stopping_rounds: int = 30
    random_state: int = 42
