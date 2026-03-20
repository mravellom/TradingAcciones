"""Train final XGBoost model and save to disk.

Trains on ALL available data (except last 10% held for monitoring).
Saves model + metadata (threshold, features, config) for production use.

Usage:
    python -m scripts.train_model
    python -m scripts.train_model --symbol BTCUSDT ETHUSDT SOLUSDT
"""
import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from app.ml.config import (
    LabelConfig, FeatureConfig, XGBoostConfig, SYMBOLS, MODELS_DIR,
)
from app.ml.data.labeler import triple_barrier_label, label_stats
from app.ml.features.pipeline import compute_features, get_feature_names
from app.ml.training.optimizer import (
    apply_volatility_filter,
    compute_class_weight,
    find_optimal_threshold,
)
from app.ml.training.evaluator import evaluate_predictions


def train_symbol(symbol: str, tp: float, sl: float, horizon: int) -> dict:
    print(f"\n{'='*60}")
    print(f"  Training: {symbol}")
    print(f"{'='*60}")

    df = pd.read_parquet(f"ml_data/raw/{symbol}_1h.parquet")
    print(f"  Data: {len(df)} rows")

    label_cfg = LabelConfig(tp_pct=tp, sl_pct=sl, horizon_bars=horizon)
    xgb_cfg = XGBoostConfig()
    feature_names = get_feature_names()

    # Compute features + labels
    features = compute_features(df)
    labeled = triple_barrier_label(df, label_cfg)

    common_idx = features.dropna().index.intersection(labeled.index)
    X = features.loc[common_idx][feature_names].replace([np.inf, -np.inf], np.nan).fillna(0)
    y = labeled.loc[common_idx]["label"]

    # Volatility filter
    X_filt, y_filt = apply_volatility_filter(df, X, y, percentile=50)
    print(f"  After vol filter: {len(X_filt)} rows, balance={y_filt.mean():.1%}")

    # Split: 90% train, 10% held for threshold tuning
    split_idx = int(len(X_filt) * 0.9)
    X_train = X_filt.iloc[:split_idx]
    y_train = y_filt.iloc[:split_idx]
    X_tune = X_filt.iloc[split_idx:]
    y_tune = y_filt.iloc[split_idx:]

    # Class weight
    class_weight = compute_class_weight(y_train)
    print(f"  Class weight: {class_weight:.2f}")

    # Train
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
    model.fit(X_train, y_train)
    print(f"  Model trained on {len(X_train)} samples")

    # Find optimal threshold
    y_tune_proba = model.predict_proba(X_tune)[:, 1]
    best_threshold, tune_metrics = find_optimal_threshold(
        y_tune.values, y_tune_proba, tp_pct=tp, sl_pct=sl
    )
    print(f"  Optimal threshold: {best_threshold:.2f}")
    print(f"  Tune metrics: {tune_metrics.summary()}")

    # Save model
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"{symbol}_xgboost.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    # Save metadata
    metadata = {
        "symbol": symbol,
        "model_type": "xgboost",
        "threshold": best_threshold,
        "features": feature_names,
        "label_config": {
            "tp_pct": tp,
            "sl_pct": sl,
            "horizon_bars": horizon,
        },
        "class_weight": class_weight,
        "vol_filter_percentile": 50,
        "train_samples": len(X_train),
        "train_date_range": f"{X_train.index[0]} to {X_train.index[-1]}",
        "tune_metrics": {
            "win_rate": tune_metrics.win_rate,
            "profit_factor": tune_metrics.profit_factor,
            "sharpe_ratio": tune_metrics.sharpe_ratio,
            "expectancy": tune_metrics.expectancy,
            "total_trades": tune_metrics.total_trades,
        },
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = MODELS_DIR / f"{symbol}_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    print(f"  Saved: {model_path}")
    print(f"  Saved: {meta_path}")

    return metadata


def main(symbols: list[str], tp: float, sl: float, horizon: int):
    print("TRAINING FINAL MODELS")
    print(f"Symbols: {symbols}")
    print(f"Config: TP={tp:.1%} SL={sl:.1%} H={horizon}")

    results = {}
    for sym in symbols:
        try:
            results[sym] = train_symbol(sym, tp, sl, horizon)
        except Exception as e:
            print(f"  ERROR training {sym}: {e}")

    print(f"\n{'='*60}")
    print("  TRAINING COMPLETE")
    print(f"{'='*60}")
    for sym, meta in results.items():
        m = meta["tune_metrics"]
        print(f"  {sym}: threshold={meta['threshold']:.2f} WR={m['win_rate']:.1%} PF={m['profit_factor']:.2f} Sharpe={m['sharpe_ratio']:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--tp", type=float, default=0.015)
    parser.add_argument("--sl", type=float, default=0.01)
    parser.add_argument("--horizon", type=int, default=24)
    args = parser.parse_args()
    main(args.symbols, args.tp, args.sl, args.horizon)
