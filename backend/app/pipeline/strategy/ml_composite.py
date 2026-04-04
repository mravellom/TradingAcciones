"""ML Composite Strategy — XGBoost (0.6) + RSI (0.2) + SMA (0.2).

All three must agree for a signal to pass (unless partial agreement is enabled).
ML provides the primary signal, RSI+SMA confirm.
"""
from decimal import Decimal
from uuid import UUID

from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.ml.serving.ml_signal_generator import MLSignalGenerator
from app.pipeline.signal_engine.atr import calculate_atr
from app.pipeline.signal_engine.composite import CompositeSignalGenerator
from app.pipeline.signal_engine.rsi import RSISignalGenerator
from app.pipeline.signal_engine.sma_crossover import SMACrossoverSignalGenerator
from app.pipeline.strategy.base import Strategy, TradeIntent


class MLCompositeStrategy(Strategy):
    """Strategy: ML (60%) + RSI (20%) + SMA (20%).

    Requires agreement between all generators (or partial if configured).
    ML weight is dominant but RSI+SMA must confirm.
    Supports ATR-based SL/TP when configured.
    """

    def __init__(
        self,
        strategy_id: UUID,
        symbol: str,
        ml_weight: float = 0.6,
        rsi_weight: float = 0.2,
        sma_weight: float = 0.2,
        min_confidence: Decimal = Decimal("0.6"),
        min_agreeing_signals: int | None = None,
        use_atr_for_sl_tp: bool = False,
        atr_period: int = 14,
        atr_sl_multiplier: Decimal = Decimal("1.5"),
        atr_tp_multiplier: Decimal = Decimal("3.0"),
    ):
        self._id = strategy_id
        self._symbol = symbol

        ml_gen = MLSignalGenerator(symbol, shadow_mode=False)

        if not ml_gen._loaded:
            raise ValueError(f"ML model not found for {symbol}")

        self._composite = CompositeSignalGenerator(
            generators=[
                (ml_gen, ml_weight),
                (RSISignalGenerator(), rsi_weight),
                (SMACrossoverSignalGenerator(), sma_weight),
            ],
            min_confidence=min_confidence,
            min_agreeing_signals=min_agreeing_signals,
        )
        self._use_atr = use_atr_for_sl_tp
        self._atr_period = atr_period
        self._atr_sl_mult = atr_sl_multiplier
        self._atr_tp_mult = atr_tp_multiplier

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def name(self) -> str:
        return f"ml_composite_{self._symbol}"

    async def evaluate(
        self, symbol: str, klines: list[Kline], timeframe: str
    ) -> TradeIntent | None:
        if symbol != self._symbol:
            return None

        signal = await self._composite.generate(symbol, klines)

        if signal is None:
            return None

        if signal.signal_type == SignalType.HOLD:
            return None

        stop_loss = signal.stop_loss
        take_profit = signal.take_profit

        # Override SL/TP with ATR if configured
        if self._use_atr:
            atr = calculate_atr(klines, self._atr_period)
            if atr and atr > 0:
                if signal.signal_type == SignalType.BUY:
                    stop_loss = signal.entry_price - (atr * self._atr_sl_mult)
                    take_profit = signal.entry_price + (atr * self._atr_tp_mult)
                else:
                    stop_loss = signal.entry_price + (atr * self._atr_sl_mult)
                    take_profit = signal.entry_price - (atr * self._atr_tp_mult)

        return TradeIntent(
            symbol=symbol,
            action=signal.signal_type,
            confidence=signal.confidence,
            entry_price=signal.entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_id=self._id,
            timeframe=timeframe,
            indicators=signal.indicators,
        )
