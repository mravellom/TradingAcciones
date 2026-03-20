"""ML-based Signal Generator.

Replaces (or complements) RSI+SMA with XGBoost predictions.
Implements the same SignalGenerator interface so it plugs
directly into CompositeSignalGenerator.
"""
from decimal import Decimal

import pandas as pd

from app.core.logging import get_logger
from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.ml.serving.predictor import ModelPredictor
from app.pipeline.signal_engine.base import SignalGenerator, SignalResult

logger = get_logger(__name__)


class MLSignalGenerator(SignalGenerator):
    """Signal generator powered by trained XGBoost model.

    - Loads model for the specific symbol
    - Converts Klines to DataFrame
    - Runs volatility filter + prediction
    - Maps probability to confidence
    - Calculates ATR-based SL/TP
    """

    def __init__(self, symbol: str, shadow_mode: bool = False):
        """
        Args:
            symbol: Trading pair (e.g. "BTCUSDT")
            shadow_mode: If True, generates signals but marks them as
                        non-executable (for monitoring without trading)
        """
        self._symbol = symbol
        self._shadow_mode = shadow_mode
        self._predictor = ModelPredictor(symbol)
        self._loaded = self._predictor.load()

        if self._loaded:
            logger.info(
                "ml_signal_generator_ready",
                symbol=symbol,
                threshold=self._predictor.threshold,
                shadow_mode=shadow_mode,
            )
        else:
            logger.warning("ml_signal_generator_no_model", symbol=symbol)

    @property
    def name(self) -> str:
        return f"ml_xgboost_{self._symbol}"

    async def generate(self, symbol: str, klines: list[Kline]) -> SignalResult | None:
        if not self._loaded:
            return None

        if symbol != self._symbol:
            return None

        if len(klines) < 60:  # Need 50+ for feature warmup
            return None

        # Convert Klines to DataFrame
        df = self._klines_to_df(klines)

        # Predict
        should_trade, probability, feature_values = self._predictor.should_trade(df)

        if not should_trade:
            return None

        # Map probability to confidence (0.55 -> 0.6, 0.80 -> 0.85)
        confidence = self._probability_to_confidence(probability)

        # ATR-based SL/TP
        current_price = df["close"].iloc[-1]
        atr = feature_values.get("atr_norm", 0.01) * current_price

        meta = self._predictor.metadata.get("label_config", {})
        tp_pct = Decimal(str(meta.get("tp_pct", 0.015)))
        sl_pct = Decimal(str(meta.get("sl_pct", 0.01)))

        entry_price = Decimal(str(current_price))
        stop_loss = entry_price * (Decimal("1") - sl_pct)
        take_profit = entry_price * (Decimal("1") + tp_pct)

        indicators = {
            "ml_probability": round(probability, 4),
            "ml_threshold": self._predictor.threshold,
            "ml_model": "xgboost",
            "shadow_mode": self._shadow_mode,
        }
        # Add top features
        for k, v in sorted(feature_values.items(), key=lambda x: abs(x[1]) if isinstance(x[1], float) else 0, reverse=True)[:5]:
            indicators[f"feat_{k}"] = round(v, 4) if isinstance(v, float) else v

        return SignalResult(
            symbol=symbol,
            signal_type=SignalType.BUY,
            confidence=confidence,
            indicators=indicators,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    @staticmethod
    def _klines_to_df(klines: list[Kline]) -> pd.DataFrame:
        data = [
            {
                "open": float(k.open),
                "high": float(k.high),
                "low": float(k.low),
                "close": float(k.close),
                "volume": float(k.volume),
            }
            for k in klines
        ]
        df = pd.DataFrame(data, index=[k.open_time for k in klines])
        df.index.name = "open_time"
        return df

    @staticmethod
    def _probability_to_confidence(probability: float) -> Decimal:
        """Map model probability [0.5-1.0] to confidence [0.6-0.90].

        Higher probability = higher confidence = larger position size.
        """
        # Linear map: 0.50 -> 0.60, 0.80 -> 0.90
        confidence = 0.60 + (probability - 0.50) * (0.30 / 0.30)
        confidence = max(0.60, min(0.90, confidence))
        return Decimal(str(round(confidence, 4)))
