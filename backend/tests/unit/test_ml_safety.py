"""Tests for ML safety features.

Validates:
- NaN ratio > 10% rejects prediction
- Model staleness detection (>30 days)
- SELL signal generation when probability < (1-threshold)
- BUY signal generation when probability > threshold
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.ml.serving.predictor import MAX_NAN_RATIO, ModelPredictor


def _make_predictor(symbol="BTCUSDT", threshold=0.6, features=None, trained_at=None):
    """Create a ModelPredictor with mocked internals."""
    predictor = ModelPredictor(symbol=symbol)

    if features is None:
        features = ["rsi_14", "sma_ratio", "volume_ratio", "atr_norm", "momentum"]

    predictor._loaded = True
    predictor._metadata = {
        "threshold": threshold,
        "features": features,
    }
    predictor._model = MagicMock()

    if trained_at is not None:
        predictor._trained_at = trained_at
    else:
        # Default: trained recently
        predictor._trained_at = datetime.now(timezone.utc) - timedelta(days=1)

    return predictor


def _make_ohlcv_df(n_rows=100):
    """Create a minimal OHLCV DataFrame."""
    dates = pd.date_range("2026-01-01", periods=n_rows, freq="1h")
    return pd.DataFrame({
        "open": np.random.uniform(49000, 51000, n_rows),
        "high": np.random.uniform(50000, 52000, n_rows),
        "low": np.random.uniform(48000, 50000, n_rows),
        "close": np.random.uniform(49000, 51000, n_rows),
        "volume": np.random.uniform(100, 10000, n_rows),
    }, index=dates)


class TestNanRejection:
    """NaN ratio > 10% should reject prediction."""

    def test_nan_ratio_above_threshold_rejects(self):
        """Prediction should return 0.0 when >10% of features are NaN."""
        features = ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10"]
        predictor = _make_predictor(features=features)

        # Create features DataFrame where 2/10 = 20% are NaN (> 10%)
        feature_row = pd.DataFrame({
            "f1": [np.nan], "f2": [np.nan],  # 2 NaN out of 10 = 20%
            "f3": [1.0], "f4": [2.0], "f5": [3.0],
            "f6": [4.0], "f7": [5.0], "f8": [6.0],
            "f9": [7.0], "f10": [8.0],
        })

        # Mock compute_features to return our controlled DataFrame
        with patch("app.ml.serving.predictor.compute_features", return_value=feature_row):
            df = _make_ohlcv_df()
            proba, info = predictor.predict(df)

        assert proba == 0.0, "Prediction should be rejected when NaN ratio > 10%"
        assert info.get("rejected") == "nan_ratio"

    def test_nan_ratio_below_threshold_accepts(self):
        """Prediction should proceed when NaN ratio <= 10%."""
        features = ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10"]
        predictor = _make_predictor(features=features)
        predictor._model.predict_proba.return_value = np.array([[0.3, 0.7]])

        # 1/10 = 10% NaN (at the boundary, should be accepted)
        feature_row = pd.DataFrame({
            "f1": [np.nan],  # 1 NaN out of 10 = 10%
            "f2": [1.0], "f3": [2.0], "f4": [3.0], "f5": [4.0],
            "f6": [5.0], "f7": [6.0], "f8": [7.0], "f9": [8.0], "f10": [9.0],
        })

        with patch("app.ml.serving.predictor.compute_features", return_value=feature_row):
            df = _make_ohlcv_df()
            proba, info = predictor.predict(df)

        assert proba == 0.7, "Prediction should proceed when NaN ratio == 10%"
        assert "rejected" not in info


class TestModelStaleness:
    """Model trained >30 days ago should be rejected."""

    def test_stale_model_detected(self):
        """Model older than max_age_days should be considered stale."""
        old_date = datetime.now(timezone.utc) - timedelta(days=35)
        predictor = _make_predictor(trained_at=old_date)

        assert predictor.is_stale(max_age_days=30) is True

    def test_fresh_model_not_stale(self):
        """Model trained recently should not be stale."""
        recent_date = datetime.now(timezone.utc) - timedelta(days=5)
        predictor = _make_predictor(trained_at=recent_date)

        assert predictor.is_stale(max_age_days=30) is False

    def test_unknown_training_date_is_stale(self):
        """Model with no training date should be considered stale."""
        predictor = _make_predictor()
        predictor._trained_at = None

        assert predictor.is_stale(max_age_days=30) is True

    def test_should_trade_rejects_stale_model(self):
        """should_trade should return HOLD for stale models."""
        old_date = datetime.now(timezone.utc) - timedelta(days=60)
        predictor = _make_predictor(trained_at=old_date)

        with patch("app.ml.serving.predictor.compute_features") as mock_cf:
            with patch("app.config.settings") as mock_settings:
                mock_settings.model_max_age_days = 30
                df = _make_ohlcv_df()
                should, direction, proba, info = predictor.should_trade(df)

        assert should is False
        assert direction == "HOLD"
        assert info.get("rejected") == "model_stale"


class TestSignalDirection:
    """BUY/SELL signal generation based on probability thresholds."""

    def test_buy_signal_when_proba_above_threshold(self):
        """probability >= threshold should generate BUY."""
        predictor = _make_predictor(threshold=0.6)
        predictor._model.predict_proba.return_value = np.array([[0.3, 0.7]])

        features = predictor._metadata["features"]
        n_features = len(features)

        # Build features DF with atr_norm for the volatility filter
        feature_data = {f: [1.0] for f in features}
        feature_df = pd.DataFrame(feature_data)
        # Add atr_norm column for volatility filter
        feature_df["atr_norm"] = 0.02

        # We need a longer atr_norm series for pct_rank calculation
        long_features = pd.DataFrame({
            **{f: np.ones(50) for f in features},
            "atr_norm": np.linspace(0.001, 0.03, 50),
        })

        call_count = [0]
        def mock_compute(df):
            call_count[0] += 1
            if call_count[0] == 1:
                return long_features  # for volatility filter
            return feature_df  # for predict

        with patch("app.ml.serving.predictor.compute_features", side_effect=mock_compute):
            with patch("app.config.settings") as mock_settings:
                mock_settings.model_max_age_days = 30
                df = _make_ohlcv_df()
                should, direction, proba, info = predictor.should_trade(df)

        assert should is True
        assert direction == "BUY"
        assert proba == 0.7

    def test_sell_signal_when_proba_below_inverse_threshold(self):
        """probability <= (1-threshold) should generate SELL."""
        predictor = _make_predictor(threshold=0.6)
        # proba = 0.35, threshold = 0.6, so 1-threshold = 0.4
        # 0.35 <= 0.4 -> SELL
        predictor._model.predict_proba.return_value = np.array([[0.65, 0.35]])

        features = predictor._metadata["features"]

        long_features = pd.DataFrame({
            **{f: np.ones(50) for f in features},
            "atr_norm": np.linspace(0.001, 0.03, 50),
        })

        feature_df = pd.DataFrame({f: [1.0] for f in features})
        feature_df["atr_norm"] = 0.02

        call_count = [0]
        def mock_compute(df):
            call_count[0] += 1
            if call_count[0] == 1:
                return long_features
            return feature_df

        with patch("app.ml.serving.predictor.compute_features", side_effect=mock_compute):
            with patch("app.config.settings") as mock_settings:
                mock_settings.model_max_age_days = 30
                df = _make_ohlcv_df()
                should, direction, proba, info = predictor.should_trade(df)

        assert should is True
        assert direction == "SELL"
        assert proba == 0.35

    def test_hold_when_proba_in_neutral_zone(self):
        """probability in the neutral zone should generate HOLD."""
        predictor = _make_predictor(threshold=0.6)
        # proba = 0.5 -- not >= 0.6 (BUY) and not <= 0.4 (SELL)
        predictor._model.predict_proba.return_value = np.array([[0.5, 0.5]])

        features = predictor._metadata["features"]

        long_features = pd.DataFrame({
            **{f: np.ones(50) for f in features},
            "atr_norm": np.linspace(0.001, 0.03, 50),
        })

        feature_df = pd.DataFrame({f: [1.0] for f in features})
        feature_df["atr_norm"] = 0.02

        call_count = [0]
        def mock_compute(df):
            call_count[0] += 1
            if call_count[0] == 1:
                return long_features
            return feature_df

        with patch("app.ml.serving.predictor.compute_features", side_effect=mock_compute):
            with patch("app.config.settings") as mock_settings:
                mock_settings.model_max_age_days = 30
                df = _make_ohlcv_df()
                should, direction, proba, info = predictor.should_trade(df)

        assert should is False
        assert direction == "HOLD"
