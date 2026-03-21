"""Model predictor: loads trained model and generates predictions.

Safety features:
- Rejects predictions when >10% of features are NaN
- Detects and rejects stale models (older than configurable threshold)
- Returns direction (BUY/SELL/HOLD) based on probability thresholds
"""
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.ml.config import MODELS_DIR
from app.ml.features.pipeline import compute_features

logger = get_logger(__name__)

MAX_NAN_RATIO = 0.10  # Reject prediction if >10% features are NaN


class ModelPredictor:
    """Loads a trained XGBoost model and predicts on new data."""

    def __init__(self, symbol: str, models_dir: Path | None = None):
        self._symbol = symbol
        self._dir = models_dir or MODELS_DIR
        self._model = None
        self._metadata = None
        self._loaded = False
        self._trained_at: datetime | None = None

    def load(self) -> bool:
        """Load model and metadata from disk."""
        model_path = self._dir / f"{self._symbol}_xgboost.pkl"
        meta_path = self._dir / f"{self._symbol}_metadata.json"

        if not model_path.exists() or not meta_path.exists():
            logger.warning("model_not_found", symbol=self._symbol, path=str(model_path))
            return False

        with open(model_path, "rb") as f:
            self._model = pickle.load(f)

        with open(meta_path, "r") as f:
            self._metadata = json.load(f)

        self._loaded = True

        # Parse and store training date for staleness detection
        trained_at_str = self._metadata.get("trained_at", "")
        if trained_at_str:
            try:
                self._trained_at = datetime.fromisoformat(trained_at_str)
                if self._trained_at.tzinfo is None:
                    self._trained_at = self._trained_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                logger.warning("model_trained_at_unparseable", symbol=self._symbol, value=trained_at_str)

        logger.info(
            "model_loaded",
            symbol=self._symbol,
            threshold=self._metadata["threshold"],
            trained_at=trained_at_str,
        )
        return True

    @property
    def threshold(self) -> float:
        return self._metadata["threshold"] if self._metadata else 0.5

    @property
    def feature_names(self) -> list[str]:
        return self._metadata["features"] if self._metadata else []

    @property
    def metadata(self) -> dict:
        return self._metadata or {}

    def is_stale(self, max_age_days: int | None = None) -> bool:
        """Check if the model is older than the maximum allowed age."""
        if max_age_days is None:
            from app.config import settings
            max_age_days = settings.model_max_age_days

        if self._trained_at is None:
            return True  # Unknown training date = stale

        age = datetime.now(timezone.utc) - self._trained_at
        return age.days > max_age_days

    def predict(self, df: pd.DataFrame) -> tuple[float, dict]:
        """Predict on OHLCV data.

        Returns:
            (probability, feature_values_dict)
        """
        if not self._loaded:
            raise RuntimeError(f"Model for {self._symbol} not loaded. Call load() first.")

        features = compute_features(df)
        if features.empty:
            return 0.0, {}

        # Get last row (most recent)
        last_features = features.iloc[-1:][self.feature_names]

        # Replace infinities with NaN for counting
        last_features = last_features.replace([np.inf, -np.inf], np.nan)

        # Validate feature quality — reject if too many NaN
        nan_count = int(last_features.isna().sum().sum())
        total_features = last_features.shape[1]
        nan_ratio = nan_count / total_features if total_features > 0 else 1.0

        if nan_ratio > MAX_NAN_RATIO:
            logger.warning(
                "prediction_rejected_nan_ratio",
                symbol=self._symbol,
                nan_count=nan_count,
                total_features=total_features,
                nan_ratio=round(nan_ratio, 3),
            )
            return 0.0, {"rejected": "nan_ratio", "nan_count": nan_count, "nan_ratio": round(nan_ratio, 3)}

        # Fill remaining NaN (<=10%) with 0 as fallback
        last_features = last_features.fillna(0)

        proba = self._model.predict_proba(last_features)[0, 1]

        feature_values = {
            name: float(last_features[name].values[0])
            for name in self.feature_names
        }

        return float(proba), feature_values

    def should_trade(self, df: pd.DataFrame) -> tuple[bool, str, float, dict]:
        """Check if model recommends trading.

        Returns:
            (should_trade, direction, probability, feature_values)
            direction is "BUY", "SELL", or "HOLD"
        """
        if not self._loaded:
            return False, "HOLD", 0.0, {}

        # Check model staleness
        if self.is_stale():
            logger.warning(
                "model_stale_rejected",
                symbol=self._symbol,
                trained_at=str(self._trained_at),
            )
            return False, "HOLD", 0.0, {"rejected": "model_stale", "trained_at": str(self._trained_at)}

        # Volatility filter using expanding window
        features = compute_features(df)
        if features.empty or "atr_norm" not in features.columns:
            return False, "HOLD", 0.0, {}

        atr_series = features["atr_norm"].dropna()
        if len(atr_series) < 2:
            return False, "HOLD", 0.0, {}

        current_atr = atr_series.iloc[-1]
        pct_rank = (atr_series < current_atr).mean()

        if pct_rank < 0.40:  # Below 40th percentile = low volatility
            return False, "HOLD", 0.0, {"filtered": "low_volatility", "atr": float(current_atr), "pct_rank": float(pct_rank)}

        proba, feature_values = self.predict(df)
        feature_values["atr_pct_rank"] = float(pct_rank)

        # Determine direction based on probability
        if proba >= self.threshold:
            direction = "BUY"
            should = True
        elif proba <= (1.0 - self.threshold):
            direction = "SELL"
            should = True
        else:
            direction = "HOLD"
            should = False

        return should, direction, proba, feature_values
