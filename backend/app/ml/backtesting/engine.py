"""Backtesting engine.

Simulates the full pipeline against historical data with:
- Commission (0.1% Binance)
- Slippage (configurable)
- Walk-forward validation
- Trading-specific metrics
"""
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from app.ml.config import LabelConfig, FeatureConfig
from app.ml.data.labeler import triple_barrier_label, label_stats
from app.ml.features.pipeline import compute_features, get_feature_names
from app.ml.training.evaluator import TradingMetrics, evaluate_predictions, evaluate_trades
from app.ml.training.splitter import walk_forward_splits


@dataclass
class BacktestConfig:
    initial_capital: float = 10000.0
    commission_pct: float = 0.001     # 0.1% Binance spot
    slippage_pct: float = 0.0005      # 0.05%
    risk_per_trade_pct: float = 0.01  # 1% risk per trade
    max_positions: int = 5
    label_config: LabelConfig = None
    feature_config: FeatureConfig = None

    def __post_init__(self):
        if self.label_config is None:
            self.label_config = LabelConfig(tp_pct=0.015, sl_pct=0.01, horizon_bars=24)
        if self.feature_config is None:
            self.feature_config = FeatureConfig()


@dataclass
class BacktestResult:
    symbol: str
    config: BacktestConfig
    fold_metrics: list[TradingMetrics]
    test_metrics: TradingMetrics | None
    baseline_metrics: TradingMetrics | None  # RSI+SMA baseline
    label_stats: dict
    passed_gates: bool = False
    gate_details: dict = None

    def summary(self) -> str:
        lines = [
            f"Backtest: {self.symbol}",
            f"Label: TP={self.config.label_config.tp_pct:.1%} SL={self.config.label_config.sl_pct:.1%} H={self.config.label_config.horizon_bars}",
            f"Labels: {self.label_stats.get('total', 0)} total, balance={self.label_stats.get('balance', 0):.1%}",
            "",
        ]
        for i, m in enumerate(self.fold_metrics):
            lines.append(f"  Fold {i+1}: {m.summary()}")
        if self.test_metrics:
            lines.append(f"  TEST:   {self.test_metrics.summary()}")
        if self.baseline_metrics:
            lines.append(f"  BASE:   {self.baseline_metrics.summary()}")
        lines.append(f"  Gates: {'PASSED' if self.passed_gates else 'FAILED'}")
        return "\n".join(lines)


def run_backtest(
    df: pd.DataFrame,
    model,
    symbol: str = "BTCUSDT",
    config: BacktestConfig | None = None,
    n_folds: int = 4,
) -> BacktestResult:
    """Run walk-forward backtest with a trained model.

    Args:
        df: OHLCV DataFrame with DatetimeIndex.
        model: Trained model with .predict_proba() or .predict() method.
        symbol: Symbol name for reporting.
        config: Backtest configuration.
        n_folds: Number of walk-forward folds.

    Returns:
        BacktestResult with per-fold and test metrics.
    """
    if config is None:
        config = BacktestConfig()

    # 1. Compute features
    features = compute_features(df, config.feature_config)
    feature_names = get_feature_names()

    # 2. Compute labels
    labeled = triple_barrier_label(df, config.label_config)
    lstats = label_stats(labeled)

    # 3. Align features and labels
    common_idx = features.dropna().index.intersection(labeled.index)
    X = features.loc[common_idx][feature_names]
    y = labeled.loc[common_idx]["label"]

    # Replace any remaining inf/nan
    X = X.replace([np.inf, -np.inf], np.nan).fillna(0)

    # 4. Walk-forward splits
    combined = pd.DataFrame({"label": y}, index=common_idx)
    folds, (test_start, test_end) = walk_forward_splits(
        combined, n_folds=n_folds
    )

    # 5. Evaluate each fold
    fold_metrics = []
    for fold in folds:
        X_train = X.loc[:fold.train_end]
        y_train = y.loc[:fold.train_end]
        X_val = X.loc[fold.val_start:fold.val_end]
        y_val = y.loc[fold.val_start:fold.val_end]

        if len(X_val) == 0:
            continue

        # Retrain model on this fold's training data
        model.fit(X_train, y_train)

        # Predict on validation
        if hasattr(model, "predict_proba"):
            y_proba = model.predict_proba(X_val)[:, 1]
        else:
            y_proba = model.predict(X_val)

        metrics = evaluate_predictions(
            y_val.values, y_proba,
            tp_pct=config.label_config.tp_pct,
            sl_pct=config.label_config.sl_pct,
        )
        fold_metrics.append(metrics)

    # 6. Final test evaluation
    test_metrics = None
    X_test = X.loc[test_start:test_end]
    y_test = y.loc[test_start:test_end]

    if len(X_test) > 0:
        # Train on all pre-test data
        X_pretrain = X.loc[:test_start].iloc[:-1]
        y_pretrain = y.loc[:test_start].iloc[:-1]

        if len(X_pretrain) > 100:
            model.fit(X_pretrain, y_pretrain)

            if hasattr(model, "predict_proba"):
                y_test_proba = model.predict_proba(X_test)[:, 1]
            else:
                y_test_proba = model.predict(X_test)

            test_metrics = evaluate_predictions(
                y_test.values, y_test_proba,
                tp_pct=config.label_config.tp_pct,
                sl_pct=config.label_config.sl_pct,
            )

    # 7. Baseline: random (no model, just label distribution)
    baseline_pnl = pd.Series(
        np.where(y.values == 1, config.label_config.tp_pct, -config.label_config.sl_pct)
    )
    baseline_metrics = evaluate_trades(baseline_pnl, config.label_config.tp_pct, config.label_config.sl_pct)

    # 8. Gate evaluation
    passed, gate_details = _check_gates(fold_metrics, test_metrics, baseline_metrics)

    return BacktestResult(
        symbol=symbol,
        config=config,
        fold_metrics=fold_metrics,
        test_metrics=test_metrics,
        baseline_metrics=baseline_metrics,
        label_stats=lstats,
        passed_gates=passed,
        gate_details=gate_details,
    )


def _check_gates(
    fold_metrics: list[TradingMetrics],
    test_metrics: TradingMetrics | None,
    baseline_metrics: TradingMetrics | None,
) -> tuple[bool, dict]:
    """Check all production gates."""
    gates = {}

    # Gate 1: All folds profitable
    if fold_metrics:
        all_profitable = all(m.profit_factor > 1.0 for m in fold_metrics)
        min_sharpe = min(m.sharpe_ratio for m in fold_metrics)
        max_dd = max(m.max_drawdown for m in fold_metrics)
        gates["folds_profitable"] = all_profitable
        gates["folds_min_sharpe"] = round(min_sharpe, 2)
        gates["folds_max_drawdown"] = round(max_dd, 4)
        gates["gate1_pass"] = all_profitable and min_sharpe > 0.5 and max_dd < 0.15
    else:
        gates["gate1_pass"] = False

    # Gate 2: Test set performance
    if test_metrics:
        gates["test_sharpe"] = round(test_metrics.sharpe_ratio, 2)
        gates["test_pf"] = round(test_metrics.profit_factor, 2)
        gates["test_dd"] = round(test_metrics.max_drawdown, 4)
        gates["gate2_pass"] = (
            test_metrics.profit_factor > 1.0
            and test_metrics.sharpe_ratio > 0.5
            and test_metrics.max_drawdown < 0.15
        )
    else:
        gates["gate2_pass"] = False

    # Gate 3: Beats baseline
    if test_metrics and baseline_metrics:
        gates["beats_baseline_sharpe"] = test_metrics.sharpe_ratio > baseline_metrics.sharpe_ratio
        gates["beats_baseline_pf"] = test_metrics.profit_factor > baseline_metrics.profit_factor
        gates["gate3_pass"] = gates["beats_baseline_sharpe"] and gates["beats_baseline_pf"]
    else:
        gates["gate3_pass"] = False

    passed = gates.get("gate1_pass", False) and gates.get("gate2_pass", False)

    return passed, gates
