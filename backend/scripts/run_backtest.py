"""Run walk-forward backtest with XGBoost + all optimizations.

Optimizations applied:
1. Volatility filter (only trade when ATR > median)
2. Class weighting (handle label imbalance)
3. Threshold tuning (optimize for expectancy, not 0.5)
4. Feature selection (drop noisy features after first pass)

Usage:
    python -m scripts.run_backtest
    python -m scripts.run_backtest --symbol ETHUSDT
    python -m scripts.run_backtest --symbol BTCUSDT --tp 0.015 --sl 0.01
"""
import argparse

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from app.ml.backtesting.engine import BacktestConfig
from app.ml.config import LabelConfig, FeatureConfig, XGBoostConfig, SYMBOLS
from app.ml.data.labeler import triple_barrier_label, label_stats
from app.ml.features.pipeline import compute_features, get_feature_names
from app.ml.training.evaluator import evaluate_predictions, TradingMetrics
from app.ml.training.optimizer import (
    apply_volatility_filter,
    compute_class_weight,
    feature_importance_filter,
    find_optimal_threshold,
)
from app.ml.training.splitter import walk_forward_splits


def main(symbol: str, tp: float, sl: float, horizon: int):
    print(f"Loading {symbol} 1h data...")
    df = pd.read_parquet(f"ml_data/raw/{symbol}_1h.parquet")
    print(f"  {len(df)} rows: {df.index[0]} to {df.index[-1]}")

    label_cfg = LabelConfig(tp_pct=tp, sl_pct=sl, horizon_bars=horizon)
    xgb_cfg = XGBoostConfig()

    # ── Step 1: Compute features + labels ──
    print("\n[1/6] Computing features...")
    features = compute_features(df)
    feature_names = get_feature_names()

    print("[2/6] Computing labels (Triple Barrier)...")
    labeled = triple_barrier_label(df, label_cfg)
    lstats = label_stats(labeled)
    print(f"  Labels: {lstats['total']} total, balance={lstats['balance']:.1%}")

    # Align
    common_idx = features.dropna().index.intersection(labeled.index)
    X_all = features.loc[common_idx][feature_names].replace([np.inf, -np.inf], np.nan).fillna(0)
    y_all = labeled.loc[common_idx]["label"]

    # ── Step 2: Volatility filter ──
    print("[3/6] Applying volatility filter (ATR > median)...")
    X_filtered, y_filtered = apply_volatility_filter(df, X_all, y_all, percentile=50)
    print(f"  Before: {len(X_all)} rows | After: {len(X_filtered)} rows ({len(X_filtered)/len(X_all):.0%})")
    print(f"  Filtered balance: {y_filtered.mean():.1%}")

    # ── Step 3: Class weight ──
    class_weight = compute_class_weight(y_filtered)
    print(f"  Class weight (scale_pos_weight): {class_weight:.2f}")

    # ── Step 4: Walk-forward splits ──
    print("[4/6] Walk-forward validation (4 folds)...")
    combined = pd.DataFrame({"label": y_filtered}, index=y_filtered.index)
    folds, (test_start, test_end) = walk_forward_splits(combined, n_folds=4)

    # ── Step 5: Train + optimize per fold ──
    print("[5/6] Training + threshold optimization per fold...\n")

    fold_metrics = []
    best_thresholds = []
    selected_features = None

    for fold in folds:
        X_train = X_filtered.loc[:fold.train_end]
        y_train = y_filtered.loc[:fold.train_end]
        X_val = X_filtered.loc[fold.val_start:fold.val_end]
        y_val = y_filtered.loc[fold.val_start:fold.val_end]

        if len(X_val) < 20:
            print(f"  Fold {fold.fold}: skipped (only {len(X_val)} val samples)")
            continue

        # Use selected features if available (from previous fold's importance)
        cols = selected_features if selected_features else feature_names

        model = XGBClassifier(
            objective=xgb_cfg.objective,
            eval_metric=xgb_cfg.eval_metric,
            max_depth=xgb_cfg.max_depth,
            min_child_weight=xgb_cfg.min_child_weight,
            subsample=xgb_cfg.subsample,
            colsample_bytree=xgb_cfg.colsample_bytree,
            learning_rate=xgb_cfg.learning_rate,
            n_estimators=xgb_cfg.n_estimators,
            reg_alpha=xgb_cfg.reg_alpha,
            reg_lambda=xgb_cfg.reg_lambda,
            scale_pos_weight=class_weight,
            random_state=xgb_cfg.random_state,
            verbosity=0,
        )

        model.fit(X_train[cols], y_train)

        # Feature selection after fold 1
        if fold.fold == 1 and selected_features is None:
            selected_features = feature_importance_filter(model, cols, min_importance=0.02)
            if len(selected_features) < 5:
                selected_features = feature_importance_filter(model, cols, min_importance=0.01)
            print(f"  Feature selection: {len(cols)} -> {len(selected_features)} features")
            print(f"  Selected: {selected_features}")

            # Retrain fold 1 with selected features
            model.fit(X_train[selected_features], y_train)
            cols = selected_features

        y_proba = model.predict_proba(X_val[cols])[:, 1]

        # Optimal threshold
        best_t, metrics = find_optimal_threshold(
            y_val.values, y_proba, tp_pct=tp, sl_pct=sl
        )
        best_thresholds.append(best_t)
        fold_metrics.append(metrics)

        print(
            f"  Fold {fold.fold}: t={best_t:.2f} | {metrics.summary()} "
            f"| train={fold.train_size} val={fold.val_size}"
        )

    # ── Step 6: Final test ──
    print(f"\n[6/6] Final out-of-sample test ({test_start[:10]} to {test_end[:10]})...")

    X_test = X_filtered.loc[test_start:test_end]
    y_test = y_filtered.loc[test_start:test_end]

    cols = selected_features or feature_names
    avg_threshold = np.mean(best_thresholds) if best_thresholds else 0.5

    test_metrics = TradingMetrics()
    if len(X_test) >= 20:
        # Train on all pre-test data
        X_pretrain = X_filtered.loc[:test_start].iloc[:-1]
        y_pretrain = y_filtered.loc[:test_start].iloc[:-1]

        final_model = XGBClassifier(
            objective=xgb_cfg.objective,
            max_depth=xgb_cfg.max_depth,
            min_child_weight=xgb_cfg.min_child_weight,
            subsample=xgb_cfg.subsample,
            colsample_bytree=xgb_cfg.colsample_bytree,
            learning_rate=xgb_cfg.learning_rate,
            n_estimators=xgb_cfg.n_estimators,
            reg_alpha=xgb_cfg.reg_alpha,
            reg_lambda=xgb_cfg.reg_lambda,
            scale_pos_weight=class_weight,
            random_state=xgb_cfg.random_state,
            verbosity=0,
        )
        final_model.fit(X_pretrain[cols], y_pretrain)
        y_test_proba = final_model.predict_proba(X_test[cols])[:, 1]

        # Use average optimal threshold from folds
        test_metrics = evaluate_predictions(
            y_test.values, y_test_proba,
            tp_pct=tp, sl_pct=sl,
            min_probability=avg_threshold,
        )

    # ── Baseline: trade everything ──
    baseline_pnl = pd.Series(
        np.where(y_filtered.values == 1, tp, -sl)
    )
    from app.ml.training.evaluator import evaluate_trades
    baseline_metrics = evaluate_trades(baseline_pnl, tp, sl)

    # ── Print results ──
    print("\n" + "=" * 70)
    print(f"  BACKTEST RESULTS: {symbol}")
    print(f"  Config: TP={tp:.1%} SL={sl:.1%} H={horizon} Ratio={tp/sl:.1f}:1")
    print(f"  Optimizations: vol_filter=ATR>p50, class_weight={class_weight:.2f}, threshold={avg_threshold:.2f}")
    print(f"  Features: {len(cols)} selected")
    print("=" * 70)

    for i, m in enumerate(fold_metrics):
        status = "PASS" if m.profit_factor > 1.0 and m.expectancy > 0 else "FAIL"
        print(f"  Fold {i+1}: {m.summary()} [{status}]")

    print(f"\n  TEST:     {test_metrics.summary()}")
    print(f"  BASELINE: {baseline_metrics.summary()}")

    # Gates
    print("\n  Gates:")
    g1 = all(m.profit_factor > 1.0 for m in fold_metrics) if fold_metrics else False
    g2 = test_metrics.profit_factor > 1.0 and test_metrics.expectancy > 0
    g3 = test_metrics.profit_factor > baseline_metrics.profit_factor if baseline_metrics.total_trades > 0 else False

    print(f"    Gate 1 (all folds PF>1):    {'PASS' if g1 else 'FAIL'}")
    print(f"    Gate 2 (test PF>1, E>0):    {'PASS' if g2 else 'FAIL'}")
    print(f"    Gate 3 (beats baseline PF): {'PASS' if g3 else 'FAIL'}")

    passed = g1 and g2
    print(f"\n  {'PASSED — viable for paper trading' if passed else 'FAILED — needs more work'}")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--tp", type=float, default=0.015)
    parser.add_argument("--sl", type=float, default=0.01)
    parser.add_argument("--horizon", type=int, default=24)
    args = parser.parse_args()

    main(args.symbol, args.tp, args.sl, args.horizon)
