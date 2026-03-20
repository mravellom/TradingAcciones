"""Model optimization: threshold tuning, volatility filter, feature selection.

Each optimization is independent and composable.
"""
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from app.ml.training.evaluator import evaluate_predictions, TradingMetrics


def find_optimal_threshold(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    tp_pct: float = 0.015,
    sl_pct: float = 0.01,
    thresholds: np.ndarray | None = None,
) -> tuple[float, TradingMetrics]:
    """Find the probability threshold that maximizes expectancy.

    Instead of using 0.5, we search for the threshold where
    the model's precision is high enough to be profitable.

    Returns (best_threshold, best_metrics).
    """
    if thresholds is None:
        thresholds = np.arange(0.40, 0.75, 0.01)

    best_threshold = 0.5
    best_metrics = TradingMetrics()
    best_score = -999.0

    for t in thresholds:
        metrics = evaluate_predictions(
            y_true, y_proba, tp_pct=tp_pct, sl_pct=sl_pct, min_probability=t
        )
        # Score by expectancy * sqrt(trades) to balance quality and quantity
        if metrics.total_trades >= 20:
            score = metrics.expectancy * np.sqrt(metrics.total_trades)
            if score > best_score:
                best_score = score
                best_threshold = float(t)
                best_metrics = metrics

    return best_threshold, best_metrics


def apply_volatility_filter(
    df: pd.DataFrame,
    features: pd.DataFrame,
    labels: pd.Series,
    percentile: float = 50,
) -> tuple[pd.DataFrame, pd.Series]:
    """Filter: only keep rows where ATR is above the percentile.

    High volatility = more room for TP to be hit.
    """
    if "atr_norm" not in features.columns:
        return features, labels

    atr = features["atr_norm"]
    # Use EXPANDING percentile (no lookahead)
    threshold = atr.expanding().quantile(percentile / 100)
    mask = atr >= threshold

    return features.loc[mask], labels.loc[mask]


def compute_class_weight(labels: pd.Series) -> float:
    """Compute scale_pos_weight for XGBoost to handle class imbalance.

    Formula: n_negative / n_positive
    """
    n_pos = (labels == 1).sum()
    n_neg = (labels == 0).sum()
    if n_pos == 0:
        return 1.0
    return float(n_neg / n_pos)


def feature_importance_filter(
    model: XGBClassifier,
    feature_names: list[str],
    min_importance: float = 0.01,
) -> list[str]:
    """Get features with importance above threshold.

    Uses XGBoost's built-in feature importance (gain-based).
    """
    importances = model.feature_importances_
    selected = []
    for name, imp in sorted(zip(feature_names, importances), key=lambda x: -x[1]):
        if imp >= min_importance:
            selected.append(name)
    return selected
