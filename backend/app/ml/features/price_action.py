"""Price action features — returns, volatility, distance to levels."""
import numpy as np
import pandas as pd


def returns(close: pd.Series, periods: list[int] = None) -> dict[str, pd.Series]:
    """Log returns over multiple periods."""
    if periods is None:
        periods = [1, 4, 24]
    result = {}
    for p in periods:
        result[f"return_{p}h"] = np.log(close / close.shift(p))
    return result


def rolling_volatility(close: pd.Series, period: int = 20) -> pd.Series:
    """Rolling standard deviation of returns, normalized by price."""
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(period).std()


def distance_to_rolling_high(close: pd.Series, period: int = 24) -> pd.Series:
    """How far current price is from recent high (drawdown indicator)."""
    rolling_max = close.rolling(period).max()
    return (close - rolling_max) / rolling_max


def distance_to_rolling_low(close: pd.Series, period: int = 24) -> pd.Series:
    """How far current price is from recent low (bounce indicator)."""
    rolling_min = close.rolling(period).min()
    return (close - rolling_min) / rolling_min
