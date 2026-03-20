"""Technical indicator features — momentum, trend, volatility.

All calculations are CAUSAL: only use data available at each point in time.
No lookahead. No future data. Rolling windows only.
"""
import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. Returns 0-100."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD line, signal line, histogram."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def stochastic_k(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Stochastic %K oscillator. Returns 0-100."""
    lowest = low.rolling(period).min()
    highest = high.rolling(period).max()
    denom = highest - lowest
    return ((close - lowest) / denom.replace(0, np.nan)) * 100


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def bollinger_bandwidth(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> pd.Series:
    """Bollinger Band width as % of price."""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return (upper - lower) / mid


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index. Measures trend strength 0-100."""
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    plus_dm = ((high - prev_high).where((high - prev_high) > (prev_low - low), 0.0)).clip(lower=0)
    minus_dm = ((prev_low - low).where((prev_low - low) > (high - prev_high), 0.0)).clip(lower=0)

    atr_val = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_val.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_val.replace(0, np.nan)

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
