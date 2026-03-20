from decimal import Decimal

from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.signal_engine.base import SignalGenerator, SignalResult

# Default parameters
DEFAULT_RSI_PERIOD = 14
DEFAULT_OVERSOLD = 30
DEFAULT_OVERBOUGHT = 70
DEFAULT_STRONG_OVERSOLD = 20
DEFAULT_STRONG_OVERBOUGHT = 80
DEFAULT_SL_PCT = Decimal("0.02")  # 2% stop loss
DEFAULT_TP_PCT = Decimal("0.04")  # 4% take profit (2:1 ratio)


class RSISignalGenerator(SignalGenerator):
    """Generates BUY/SELL signals based on RSI levels.

    - RSI < oversold → BUY signal
    - RSI > overbought → SELL signal
    - Confidence scales with RSI extremity
    """

    def __init__(
        self,
        period: int = DEFAULT_RSI_PERIOD,
        oversold: float = DEFAULT_OVERSOLD,
        overbought: float = DEFAULT_OVERBOUGHT,
        sl_pct: Decimal = DEFAULT_SL_PCT,
        tp_pct: Decimal = DEFAULT_TP_PCT,
    ):
        self._period = period
        self._oversold = oversold
        self._overbought = overbought
        self._sl_pct = sl_pct
        self._tp_pct = tp_pct

    @property
    def name(self) -> str:
        return "rsi"

    async def generate(self, symbol: str, klines: list[Kline]) -> SignalResult | None:
        if len(klines) < self._period + 1:
            return None

        rsi_value = self._calculate_rsi(klines)
        if rsi_value is None:
            return None

        current_price = klines[-1].close

        # Oversold → BUY
        if rsi_value < self._oversold:
            confidence = self._buy_confidence(rsi_value)
            return SignalResult(
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                indicators={"rsi": float(rsi_value), "period": self._period},
                entry_price=current_price,
                stop_loss=current_price * (Decimal("1") - self._sl_pct),
                take_profit=current_price * (Decimal("1") + self._tp_pct),
            )

        # Overbought → SELL
        if rsi_value > self._overbought:
            confidence = self._sell_confidence(rsi_value)
            return SignalResult(
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                indicators={"rsi": float(rsi_value), "period": self._period},
                entry_price=current_price,
                stop_loss=current_price * (Decimal("1") + self._sl_pct),
                take_profit=current_price * (Decimal("1") - self._tp_pct),
            )

        return None

    def _calculate_rsi(self, klines: list[Kline]) -> float | None:
        """Calculate RSI from closing prices."""
        closes = [float(k.close) for k in klines]

        if len(closes) < self._period + 1:
            return None

        # Calculate price changes
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

        # Initial average gain/loss
        gains = [d if d > 0 else 0 for d in deltas[: self._period]]
        losses = [-d if d < 0 else 0 for d in deltas[: self._period]]

        avg_gain = sum(gains) / self._period
        avg_loss = sum(losses) / self._period

        # Smoothed RSI (Wilder's method)
        for d in deltas[self._period :]:
            gain = d if d > 0 else 0
            loss = -d if d < 0 else 0
            avg_gain = (avg_gain * (self._period - 1) + gain) / self._period
            avg_loss = (avg_loss * (self._period - 1) + loss) / self._period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 2)

    def _buy_confidence(self, rsi: float) -> Decimal:
        """Map RSI to confidence. Lower RSI = higher confidence."""
        if rsi <= DEFAULT_STRONG_OVERSOLD:
            return Decimal("0.85")
        # Linear scale from oversold to strong_oversold
        ratio = (self._oversold - rsi) / (self._oversold - DEFAULT_STRONG_OVERSOLD)
        confidence = 0.6 + (ratio * 0.25)
        return Decimal(str(round(min(max(confidence, 0.6), 0.85), 4)))

    def _sell_confidence(self, rsi: float) -> Decimal:
        """Map RSI to confidence. Higher RSI = higher confidence."""
        if rsi >= DEFAULT_STRONG_OVERBOUGHT:
            return Decimal("0.85")
        ratio = (rsi - self._overbought) / (DEFAULT_STRONG_OVERBOUGHT - self._overbought)
        confidence = 0.6 + (ratio * 0.25)
        return Decimal(str(round(min(max(confidence, 0.6), 0.85), 4)))
