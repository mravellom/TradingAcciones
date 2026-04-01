"""Train XGBoost model for US stocks and save to disk.

Downloads historical data from Alpaca, computes features, labels,
and trains per-symbol models with stock-specific parameters.

Usage:
    python -m scripts.train_stock_model
    python -m scripts.train_stock_model --symbols AAPL MSFT NVDA
    python -m scripts.train_stock_model --download-only
"""
import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.ml.config import (
    MODELS_DIR,
    RAW_DIR,
    STOCK_SYMBOLS,
    STOCK_PRIMARY_TIMEFRAME,
    StockFeatureConfig,
    StockLabelConfig,
    XGBoostConfig,
)
from app.ml.data.labeler import triple_barrier_label, label_stats
from app.ml.features.pipeline import compute_features, get_feature_names
from app.ml.training.optimizer import (
    apply_volatility_filter,
    compute_class_weight,
    find_optimal_threshold,
)
from app.ml.training.evaluator import evaluate_predictions


def download_stock_data(symbols: list[str]) -> None:
    """Download historical stock data from Alpaca (sync wrapper)."""
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.config import settings

    if not settings.alpaca_api_key:
        print("ERROR: ALPACA_API_KEY not set. Cannot download stock data.")
        print("Set ALPACA_API_KEY and ALPACA_API_SECRET in .env")
        return

    async def _download():
        engine = create_async_engine(settings.database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with session_factory() as session:
            from app.ml.data.downloader import HistoricalDataDownloader
            dl = HistoricalDataDownloader(session)

            for symbol in symbols:
                for interval in [STOCK_PRIMARY_TIMEFRAME, "1h"]:
                    try:
                        count = await dl.download_stock_symbol(symbol, interval)
                        print(f"  {symbol} ({interval}): {count} new bars")
                    except Exception as e:
                        print(f"  {symbol} ({interval}): ERROR - {e}")

            # Export to parquet
            for symbol in symbols:
                try:
                    path = await dl.export_to_parquet(symbol, STOCK_PRIMARY_TIMEFRAME)
                    print(f"  Exported: {path}")
                except Exception as e:
                    print(f"  {symbol} parquet export: {e}")

        await engine.dispose()

    print("DOWNLOADING STOCK DATA FROM ALPACA")
    print(f"Symbols: {symbols}")
    asyncio.run(_download())


def train_stock_symbol(symbol: str) -> dict | None:
    """Train a model for a single stock symbol."""
    label_cfg = StockLabelConfig()
    xgb_cfg = XGBoostConfig()
    feature_names = get_feature_names()

    parquet_path = RAW_DIR / f"{symbol}_{STOCK_PRIMARY_TIMEFRAME}.parquet"
    if not parquet_path.exists():
        print(f"  No data for {symbol} at {parquet_path}")
        return None

    print(f"\n{'='*60}")
    print(f"  Training: {symbol} (STOCKS)")
    print(f"{'='*60}")

    df = pd.read_parquet(parquet_path)
    print(f"  Data: {len(df)} rows ({df.index[0]} to {df.index[-1]})")

    if len(df) < 200:
        print(f"  Insufficient data ({len(df)} rows, need 200+)")
        return None

    # Compute features + labels
    features = compute_features(df)
    labeled = triple_barrier_label(
        df,
        label_cfg=type("LC", (), {
            "tp_pct": label_cfg.tp_pct,
            "sl_pct": label_cfg.sl_pct,
            "horizon_bars": label_cfg.horizon_bars,
            "min_samples_per_class": label_cfg.min_samples_per_class,
        })(),
    )

    common_idx = features.dropna().index.intersection(labeled.index)
    X = features.loc[common_idx][feature_names].replace([np.inf, -np.inf], np.nan).fillna(0)
    y = labeled.loc[common_idx]["label"]

    print(f"  Features: {len(X)} rows, {len(feature_names)} features")
    print(f"  Label balance: {y.mean():.1%} positive")

    if len(X) < 100:
        print(f"  Too few samples after feature computation")
        return None

    # Volatility filter (less aggressive for stocks — 30th percentile)
    X_filt, y_filt = apply_volatility_filter(df, X, y, percentile=30)
    print(f"  After vol filter: {len(X_filt)} rows")

    # Split: 90% train, 10% tune
    split_idx = int(len(X_filt) * 0.9)
    X_train = X_filt.iloc[:split_idx]
    y_train = y_filt.iloc[:split_idx]
    X_tune = X_filt.iloc[split_idx:]
    y_tune = y_filt.iloc[split_idx:]

    if len(X_tune) < 20:
        print(f"  Too few tuning samples ({len(X_tune)})")
        return None

    class_weight = compute_class_weight(y_train)
    print(f"  Class weight: {class_weight:.2f}")

    # Train XGBoost
    from xgboost import XGBClassifier
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
    print(f"  Trained on {len(X_train)} samples")

    # Find optimal threshold
    y_tune_proba = model.predict_proba(X_tune)[:, 1]
    best_threshold, tune_metrics = find_optimal_threshold(
        y_tune.values, y_tune_proba,
        tp_pct=label_cfg.tp_pct,
        sl_pct=label_cfg.sl_pct,
    )
    print(f"  Threshold: {best_threshold:.2f}")
    print(f"  Metrics: {tune_metrics.summary()}")

    # Save
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"{symbol}_stock_xgboost.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    metadata = {
        "symbol": symbol,
        "asset_class": "STOCKS",
        "model_type": "xgboost",
        "threshold": best_threshold,
        "features": feature_names,
        "label_config": {
            "tp_pct": label_cfg.tp_pct,
            "sl_pct": label_cfg.sl_pct,
            "horizon_bars": label_cfg.horizon_bars,
        },
        "class_weight": class_weight,
        "vol_filter_percentile": 30,
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
    meta_path = MODELS_DIR / f"{symbol}_stock_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    print(f"  Saved: {model_path}")
    return metadata


def main(symbols: list[str], download: bool, train: bool):
    if download:
        download_stock_data(symbols)

    if not train:
        return

    print(f"\nTRAINING STOCK MODELS")
    label_cfg = StockLabelConfig()
    print(f"Label config: TP={label_cfg.tp_pct:.2%} SL={label_cfg.sl_pct:.2%} H={label_cfg.horizon_bars}")

    results = {}
    for sym in symbols:
        try:
            meta = train_stock_symbol(sym)
            if meta:
                results[sym] = meta
        except Exception as e:
            print(f"  ERROR training {sym}: {e}")

    print(f"\n{'='*60}")
    print("  STOCK TRAINING COMPLETE")
    print(f"{'='*60}")
    for sym, meta in results.items():
        m = meta["tune_metrics"]
        print(f"  {sym}: threshold={meta['threshold']:.2f} WR={m['win_rate']:.1%} PF={m['profit_factor']:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train stock ML models")
    parser.add_argument("--symbols", nargs="+", default=STOCK_SYMBOLS)
    parser.add_argument("--download-only", action="store_true", help="Only download data, skip training")
    parser.add_argument("--train-only", action="store_true", help="Only train, skip download")
    args = parser.parse_args()

    do_download = not args.train_only
    do_train = not args.download_only
    main(args.symbols, do_download, do_train)
