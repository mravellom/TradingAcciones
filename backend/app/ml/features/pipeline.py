"""Feature pipeline — combines all feature groups.

CRITICAL RULE: Every feature is calculated using ONLY past data.
No lookahead. No future information. Everything is causal.

The pipeline takes raw OHLCV and returns a feature matrix ready for ML.
"""
import pandas as pd
import numpy as np

from app.ml.features import technical as ta
from app.ml.features import price_action as pa
from app.ml.features import volume as vol
from app.ml.features import temporal as temp
from app.ml.config import FeatureConfig

# Features that will be computed
FEATURE_COLUMNS = [
    # Momentum (5)
    "rsi_7", "rsi_14",
    "macd_histogram",
    "macd_cross",  # 1 if MACD > signal, 0 otherwise
    "stoch_k",
    # Trend (4)
    "sma_ratio",  # sma_fast / sma_slow
    "ema_ratio",  # ema_fast / ema_slow
    "adx",
    "price_vs_sma50",  # (price - sma50) / sma50
    # Volatility (3)
    "atr_norm",  # ATR / price
    "bb_width",
    "rolling_vol",
    # Volume (3)
    "rel_volume",
    "obv_slope",
    "vol_price_corr",
    # Price Action (4)
    "return_1h", "return_4h", "return_24h",
    "dd_from_high",  # distance to 24h high
    # Temporal (4)
    "hour_sin", "hour_cos",
    "dow_sin", "dow_cos",
]


def compute_features(
    df: pd.DataFrame,
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    """Compute all features from OHLCV data.

    Args:
        df: DataFrame with columns [open, high, low, close, volume].
            Index must be DatetimeIndex.
        config: Feature parameters.

    Returns:
        DataFrame with feature columns added. NaN rows at the start
        (due to rolling windows) are NOT dropped — caller decides.
    """
    if config is None:
        config = FeatureConfig()

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    features = pd.DataFrame(index=df.index)

    # ── Momentum ──
    features["rsi_7"] = ta.rsi(close, 7)
    features["rsi_14"] = ta.rsi(close, 14)

    macd_line, signal_line, histogram = ta.macd(close)
    features["macd_histogram"] = histogram
    features["macd_cross"] = (macd_line > signal_line).astype(float)

    features["stoch_k"] = ta.stochastic_k(high, low, close)

    # ── Trend ──
    sma_fast = ta.sma(close, config.sma_fast)
    sma_slow = ta.sma(close, config.sma_slow)
    features["sma_ratio"] = sma_fast / sma_slow.replace(0, np.nan)

    ema_fast = ta.ema(close, config.ema_fast)
    ema_slow = ta.ema(close, config.ema_slow)
    features["ema_ratio"] = ema_fast / ema_slow.replace(0, np.nan)

    features["adx"] = ta.adx(high, low, close, config.adx_period)

    sma_50 = ta.sma(close, 50)
    features["price_vs_sma50"] = (close - sma_50) / sma_50.replace(0, np.nan)

    # ── Volatility ──
    atr_val = ta.atr(high, low, close, config.atr_period)
    features["atr_norm"] = atr_val / close.replace(0, np.nan)

    features["bb_width"] = ta.bollinger_bandwidth(close, config.bb_period)
    features["rolling_vol"] = pa.rolling_volatility(close, config.rolling_std_period)

    # ── Volume ──
    features["rel_volume"] = vol.relative_volume(volume, config.volume_ma_period)
    features["obv_slope"] = vol.obv_slope(close, volume, config.obv_slope_period)
    features["vol_price_corr"] = vol.volume_price_trend(close, volume)

    # ── Price Action ──
    ret = pa.returns(close, [1, 4, 24])
    features["return_1h"] = ret["return_1h"]
    features["return_4h"] = ret["return_4h"]
    features["return_24h"] = ret["return_24h"]
    features["dd_from_high"] = pa.distance_to_rolling_high(close, 24)

    # ── Temporal ──
    hour_feats = temp.hour_features(df.index)
    features["hour_sin"] = hour_feats["hour_sin"]
    features["hour_cos"] = hour_feats["hour_cos"]

    dow_feats = temp.day_of_week_features(df.index)
    features["dow_sin"] = dow_feats["dow_sin"]
    features["dow_cos"] = dow_feats["dow_cos"]

    return features


def prepare_dataset(
    df: pd.DataFrame,
    config: FeatureConfig | None = None,
    dropna: bool = True,
) -> pd.DataFrame:
    """Compute features and merge with OHLCV. Optionally drop NaN rows.

    Returns DataFrame with both OHLCV and feature columns.
    """
    features = compute_features(df, config)
    result = pd.concat([df, features], axis=1)
    if dropna:
        result = result.dropna()
    return result


def get_feature_names() -> list[str]:
    """Return the list of feature column names."""
    return FEATURE_COLUMNS.copy()
