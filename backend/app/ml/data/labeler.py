"""Triple Barrier Labeling.

Labels each bar with 1 (profitable trade) or 0 (losing trade / timeout)
based on whether price hits Take Profit before Stop Loss within a time horizon.

This aligns the ML target with the real trading pipeline's SL/TP logic.
"""
import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.ml.config import LabelConfig

logger = get_logger(__name__)


def triple_barrier_label(
    df: pd.DataFrame,
    config: LabelConfig | None = None,
) -> pd.DataFrame:
    """Apply Triple Barrier Labeling to OHLCV data.

    Args:
        df: DataFrame with columns [open, high, low, close, volume].
            Index must be datetime.
        config: Labeling parameters (tp_pct, sl_pct, horizon_bars).

    Returns:
        DataFrame with added columns:
        - label: 1 (TP hit first) or 0 (SL hit first or timeout)
        - barrier_hit: "tp", "sl", or "timeout"
        - bars_to_hit: number of bars until barrier was hit
        - max_favorable: maximum favorable excursion (%)
        - max_adverse: maximum adverse excursion (%)
    """
    if config is None:
        config = LabelConfig()

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(closes)

    labels = np.zeros(n, dtype=np.int32)
    barriers = np.empty(n, dtype="U10")
    bars_to_hit = np.zeros(n, dtype=np.int32)
    max_favorable = np.zeros(n, dtype=np.float64)
    max_adverse = np.zeros(n, dtype=np.float64)

    for i in range(n):
        entry = closes[i]
        if entry <= 0:
            barriers[i] = "invalid"
            continue

        tp_price = entry * (1 + config.tp_pct)
        sl_price = entry * (1 - config.sl_pct)

        horizon_end = min(i + config.horizon_bars, n)

        # Default: timeout
        hit = "timeout"
        hit_bar = config.horizon_bars
        mfe = 0.0  # max favorable excursion
        mae = 0.0  # max adverse excursion

        for j in range(i + 1, horizon_end):
            # Track excursions
            high_pct = (highs[j] - entry) / entry
            low_pct = (entry - lows[j]) / entry

            if high_pct > mfe:
                mfe = high_pct
            if low_pct > mae:
                mae = low_pct

            # Check barriers (using high/low for more accurate detection)
            tp_hit = highs[j] >= tp_price
            sl_hit = lows[j] <= sl_price

            if tp_hit and sl_hit:
                # Both hit in same bar — use close to decide
                # Conservative: if close is above entry, TP; otherwise SL
                if closes[j] >= entry:
                    hit = "tp"
                else:
                    hit = "sl"
                hit_bar = j - i
                break
            elif tp_hit:
                hit = "tp"
                hit_bar = j - i
                break
            elif sl_hit:
                hit = "sl"
                hit_bar = j - i
                break

        labels[i] = 1 if hit == "tp" else 0
        barriers[i] = hit
        bars_to_hit[i] = hit_bar
        max_favorable[i] = mfe
        max_adverse[i] = mae

    result = df.copy()
    result["label"] = labels
    result["barrier_hit"] = barriers
    result["bars_to_hit"] = bars_to_hit
    result["max_favorable"] = max_favorable
    result["max_adverse"] = max_adverse

    # Remove last horizon_bars rows (incomplete labels)
    result = result.iloc[:-config.horizon_bars]

    return result


def label_stats(df: pd.DataFrame) -> dict:
    """Get statistics about the labeled dataset."""
    total = len(df)
    if total == 0:
        return {"total": 0}

    tp_count = (df["barrier_hit"] == "tp").sum()
    sl_count = (df["barrier_hit"] == "sl").sum()
    timeout_count = (df["barrier_hit"] == "timeout").sum()

    positive = (df["label"] == 1).sum()
    negative = (df["label"] == 0).sum()

    return {
        "total": total,
        "positive (label=1)": int(positive),
        "negative (label=0)": int(negative),
        "balance": round(positive / total, 4) if total > 0 else 0,
        "tp_hit": int(tp_count),
        "sl_hit": int(sl_count),
        "timeout": int(timeout_count),
        "tp_pct": round(tp_count / total, 4),
        "sl_pct": round(sl_count / total, 4),
        "timeout_pct": round(timeout_count / total, 4),
        "avg_bars_to_hit": round(df["bars_to_hit"].mean(), 2),
        "avg_max_favorable": round(df["max_favorable"].mean() * 100, 4),
        "avg_max_adverse": round(df["max_adverse"].mean() * 100, 4),
    }
