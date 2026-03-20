"""Walk-forward temporal data splitter.

Ensures NO data leakage: train always before validation.
Each fold expands the training window and slides the validation window.
"""
from dataclasses import dataclass

import pandas as pd


@dataclass
class SplitFold:
    fold: int
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    train_size: int = 0
    val_size: int = 0


def walk_forward_splits(
    df: pd.DataFrame,
    n_folds: int = 4,
    val_size_pct: float = 0.10,
    test_size_pct: float = 0.10,
) -> tuple[list[SplitFold], tuple[str, str]]:
    """Generate walk-forward splits for time series.

    Args:
        df: DataFrame with DatetimeIndex, sorted by time.
        n_folds: Number of train/val folds.
        val_size_pct: Fraction of data for each validation window.
        test_size_pct: Fraction of data held out for final test.

    Returns:
        (folds, (test_start, test_end))
    """
    n = len(df)
    test_size = int(n * test_size_pct)
    trainval_size = n - test_size

    val_size = int(trainval_size * val_size_pct)
    step = (trainval_size - val_size) // n_folds

    folds = []
    for i in range(n_folds):
        train_end_idx = (i + 1) * step + val_size  # expanding window
        val_start_idx = train_end_idx
        val_end_idx = min(val_start_idx + val_size, trainval_size)

        if val_start_idx >= trainval_size:
            break

        train_slice = df.iloc[:train_end_idx]
        val_slice = df.iloc[val_start_idx:val_end_idx]

        fold = SplitFold(
            fold=i + 1,
            train_start=str(train_slice.index[0]),
            train_end=str(train_slice.index[-1]),
            val_start=str(val_slice.index[0]),
            val_end=str(val_slice.index[-1]),
            train_size=len(train_slice),
            val_size=len(val_slice),
        )
        folds.append(fold)

    # Test set = last test_size_pct
    test_start = str(df.index[trainval_size])
    test_end = str(df.index[-1])

    return folds, (test_start, test_end)


def split_by_dates(
    df: pd.DataFrame,
    train_end: str,
    val_end: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    """Split by explicit dates.

    Returns (train, val, test_or_none).
    """
    train = df.loc[:train_end]
    if val_end:
        val = df.loc[train_end:val_end].iloc[1:]  # exclude train_end
        test = df.loc[val_end:].iloc[1:]
        return train, val, test
    else:
        val = df.loc[train_end:].iloc[1:]
        return train, val, None
