"""Temporal features — cyclical encoding of time."""
import numpy as np
import pandas as pd


def hour_features(index: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """Cyclical encoding of hour of day (UTC)."""
    hours = index.hour
    return {
        "hour_sin": pd.Series(np.sin(2 * np.pi * hours / 24), index=index),
        "hour_cos": pd.Series(np.cos(2 * np.pi * hours / 24), index=index),
    }


def day_of_week_features(index: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """Cyclical encoding of day of week."""
    days = index.dayofweek
    return {
        "dow_sin": pd.Series(np.sin(2 * np.pi * days / 7), index=index),
        "dow_cos": pd.Series(np.cos(2 * np.pi * days / 7), index=index),
    }
