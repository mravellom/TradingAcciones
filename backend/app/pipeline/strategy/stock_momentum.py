"""Stock-tuned momentum strategy.

Key differences from crypto momentum:
- RSI thresholds are tighter (stocks are less volatile)
- SMA periods are longer (stocks trend slower)
- SL/TP are smaller (stocks move ~1% daily vs crypto 3-5%)
- RSI weight is higher (mean-reversion works better in stocks)
"""
from decimal import Decimal
from uuid import UUID

from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.signal_engine.atr import calculate_atr
from app.pipeline.signal_engine.composite import CompositeSignalGenerator
from app.pipeline.signal_engine.rsi import RSISignalGenerator
from app.pipeline.signal_engine.sma_crossover import SMACrossoverSignalGenerator
from app.pipeline.strategy.base import Strategy, TradeIntent

# Stock-specific RSI thresholds
STOCK_RSI_PERIOD = 14
STOCK_RSI_OVERSOLD = 35       # 35 vs 30 for crypto (less extreme)
STOCK_RSI_OVERBOUGHT = 65     # 65 vs 70 for crypto
STOCK_RSI_SL_PCT = Decimal("0.015")  # 1.5% SL (vs 2% crypto)
STOCK_RSI_TP_PCT = Decimal("0.03")   # 3% TP (vs 4% crypto, keeps 2:1 ratio)

# Stock-specific SMA periods
STOCK_SMA_FAST = 10     # 10 vs 9 (slightly slower)
STOCK_SMA_SLOW = 30     # 30 vs 21 (catches larger trends)
STOCK_SMA_SL_PCT = Decimal("0.015")
STOCK_SMA_TP_PCT = Decimal("0.03")


class StockMomentumStrategy(Strategy):
    """Momentum strategy tuned for US stocks.

    Differences from crypto MomentumStrategy:
    - RSI: oversold=35, overbought=65 (stocks mean-revert earlier)
    - SMA: 10/30 crossover (stocks trend slower than crypto)
    - SL/TP: 1.5%/3% (stocks are less volatile)
    - RSI weight 0.5, SMA weight 0.5 (equal weighting)
    - Supports ATR-based SL/TP when configured.
    """

    def __init__(
        self,
        strategy_id: UUID,
        rsi_period: int = STOCK_RSI_PERIOD,
        rsi_oversold: float = STOCK_RSI_OVERSOLD,
        rsi_overbought: float = STOCK_RSI_OVERBOUGHT,
        sma_fast: int = STOCK_SMA_FAST,
        sma_slow: int = STOCK_SMA_SLOW,
        rsi_weight: float = 0.5,
        sma_weight: float = 0.5,
        min_confidence: Decimal = Decimal("0.6"),
        min_agreeing_signals: int | None = None,
        use_atr_for_sl_tp: bool = False,
        atr_period: int = 14,
        atr_sl_multiplier: Decimal = Decimal("1.5"),
        atr_tp_multiplier: Decimal = Decimal("3.0"),
    ):
        self._id = strategy_id
        self._composite = CompositeSignalGenerator(
            generators=[
                (
                    RSISignalGenerator(
                        period=rsi_period,
                        oversold=rsi_oversold,
                        overbought=rsi_overbought,
                        sl_pct=STOCK_RSI_SL_PCT,
                        tp_pct=STOCK_RSI_TP_PCT,
                    ),
                    rsi_weight,
                ),
                (
                    SMACrossoverSignalGenerator(
                        fast_period=sma_fast,
                        slow_period=sma_slow,
                        sl_pct=STOCK_SMA_SL_PCT,
                        tp_pct=STOCK_SMA_TP_PCT,
                    ),
                    sma_weight,
                ),
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
        return "stock_momentum"

    async def evaluate(
        self, symbol: str, klines: list[Kline], timeframe: str
    ) -> TradeIntent | None:
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
