from decimal import Decimal
from uuid import UUID

from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.signal_engine.composite import CompositeSignalGenerator
from app.pipeline.signal_engine.rsi import RSISignalGenerator
from app.pipeline.signal_engine.sma_crossover import SMACrossoverSignalGenerator
from app.pipeline.strategy.base import Strategy, TradeIntent


class MomentumStrategy(Strategy):
    """Momentum strategy combining RSI and SMA crossover.

    - Uses CompositeSignalGenerator to combine signals.
    - RSI weight: 0.4, SMA weight: 0.6
    - Only generates BUY signals (spot, no shorting).
    """

    def __init__(
        self,
        strategy_id: UUID,
        rsi_period: int = 14,
        sma_fast: int = 9,
        sma_slow: int = 21,
        rsi_weight: float = 0.4,
        sma_weight: float = 0.6,
        min_confidence: Decimal = Decimal("0.6"),
    ):
        self._id = strategy_id
        self._composite = CompositeSignalGenerator(
            generators=[
                (RSISignalGenerator(period=rsi_period), rsi_weight),
                (SMACrossoverSignalGenerator(fast_period=sma_fast, slow_period=sma_slow), sma_weight),
            ],
            min_confidence=min_confidence,
        )

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def name(self) -> str:
        return "momentum"

    async def evaluate(
        self, symbol: str, klines: list[Kline], timeframe: str
    ) -> TradeIntent | None:
        signal = await self._composite.generate(symbol, klines)

        if signal is None:
            return None

        # For spot trading, only act on BUY signals
        # SELL signals will be handled by position manager (close existing positions)
        if signal.signal_type == SignalType.HOLD:
            return None

        return TradeIntent(
            symbol=symbol,
            action=signal.signal_type,
            confidence=signal.confidence,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            strategy_id=self._id,
            timeframe=timeframe,
            indicators=signal.indicators,
        )
