"""Average True Range (ATR) calculator for dynamic SL/TP."""
from decimal import Decimal

from app.exchange.base import Kline

DEFAULT_ATR_PERIOD = 14


def calculate_atr(klines: list[Kline], period: int = DEFAULT_ATR_PERIOD) -> Decimal | None:
    """Calculate ATR using Wilder's smoothing method.

    Requires at least period + 1 klines.
    Returns None if insufficient data.
    """
    if len(klines) < period + 1:
        return None

    # True Range for each candle (skip first — no previous close)
    true_ranges: list[float] = []
    for i in range(1, len(klines)):
        high = float(klines[i].high)
        low = float(klines[i].low)
        prev_close = float(klines[i - 1].close)

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    # Initial ATR: simple average of first `period` TRs
    atr = sum(true_ranges[:period]) / period

    # Wilder's smoothing for remaining TRs
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period

    return Decimal(str(round(atr, 8)))
