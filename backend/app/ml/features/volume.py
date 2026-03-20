"""Volume-based features."""
import numpy as np
import pandas as pd


def relative_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    """Current volume / average volume. >1 = above average activity."""
    avg = volume.rolling(period).mean()
    return volume / avg.replace(0, np.nan)


def obv_slope(close: pd.Series, volume: pd.Series, period: int = 10) -> pd.Series:
    """On-Balance Volume slope (direction of smart money)."""
    direction = np.sign(close.diff())
    obv = (volume * direction).cumsum()
    # Slope = linear regression slope over last N periods
    return obv.diff(period) / period


def volume_price_trend(close: pd.Series, volume: pd.Series, period: int = 10) -> pd.Series:
    """Correlation between price change and volume over rolling window."""
    price_change = close.pct_change()
    return price_change.rolling(period).corr(volume)
