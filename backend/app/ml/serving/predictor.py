"""Model predictor: loads trained model and generates predictions."""
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.ml.config import MODELS_DIR
from app.ml.features.pipeline import compute_features

logger = get_logger(__name__)


class ModelPredictor:
    """Loads a trained XGBoost model and predicts on new data."""

    def __init__(self, symbol: str, models_dir: Path | None = None):
        self._symbol = symbol
        self._dir = models_dir or MODELS_DIR
        self._model = None
        self._metadata = None
        self._loaded = False

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
        logger.info(
            "model_loaded",
            symbol=self._symbol,
            threshold=self._metadata["threshold"],
            trained_at=self._metadata["trained_at"],
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

    def predict(self, df: pd.DataFrame) -> tuple[float, dict]:
        """Predict on OHLCV data.

        Args:
            df: Recent OHLCV data (at least 50 rows for feature warmup).

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
        last_features = last_features.replace([np.inf, -np.inf], np.nan).fillna(0)

        proba = self._model.predict_proba(last_features)[0, 1]

        feature_values = {
            name: float(last_features[name].values[0])
            for name in self.feature_names
        }

        return float(proba), feature_values

    def should_trade(self, df: pd.DataFrame) -> tuple[bool, float, dict]:
        """Check if model recommends trading.

        Volatility filter: ATR must be in upper half historically.
        Uses expanding percentile (not just current window) for robustness.

        Returns:
            (should_trade, probability, feature_values)
        """
        if not self._loaded:
            return False, 0.0, {}

        # Volatility filter using expanding window
        features = compute_features(df)
        if features.empty or "atr_norm" not in features.columns:
            return False, 0.0, {}

        atr_series = features["atr_norm"].dropna()
        if len(atr_series) < 2:
            return False, 0.0, {}

        current_atr = atr_series.iloc[-1]
        # Use percentile rank: what % of historical ATR is below current?
        pct_rank = (atr_series < current_atr).mean()

        if pct_rank < 0.40:  # Below 40th percentile = low volatility
            return False, 0.0, {"filtered": "low_volatility", "atr": float(current_atr), "pct_rank": float(pct_rank)}

        proba, feature_values = self.predict(df)
        feature_values["atr_pct_rank"] = float(pct_rank)

        return proba >= self.threshold, proba, feature_values
