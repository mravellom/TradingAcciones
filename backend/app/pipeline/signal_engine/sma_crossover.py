from decimal import Decimal

from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.signal_engine.base import SignalGenerator, SignalResult

DEFAULT_FAST_PERIOD = 9
DEFAULT_SLOW_PERIOD = 21
DEFAULT_SL_PCT = Decimal("0.02")
DEFAULT_TP_PCT = Decimal("0.04")


class SMACrossoverSignalGenerator(SignalGenerator):
    """Generates signals based on SMA crossover.

    - Fast SMA crosses above Slow SMA → BUY (golden cross)
    - Fast SMA crosses below Slow SMA → SELL (death cross)
    - Confidence based on separation distance between SMAs
    """

    def __init__(
        self,
        fast_period: int = DEFAULT_FAST_PERIOD,
        slow_period: int = DEFAULT_SLOW_PERIOD,
        sl_pct: Decimal = DEFAULT_SL_PCT,
        tp_pct: Decimal = DEFAULT_TP_PCT,
    ):
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._sl_pct = sl_pct
        self._tp_pct = tp_pct

    @property
    def name(self) -> str:
        return "sma_crossover"

    async def generate(self, symbol: str, klines: list[Kline]) -> SignalResult | None:
        if len(klines) < self._slow_period + 2:  # Need at least 2 periods for crossover detection
            return None

        closes = [float(k.close) for k in klines]

        # Calculate current and previous SMAs
        fast_current = self._sma(closes, self._fast_period, offset=0)
        fast_prev = self._sma(closes, self._fast_period, offset=1)
        slow_current = self._sma(closes, self._slow_period, offset=0)
        slow_prev = self._sma(closes, self._slow_period, offset=1)

        current_price = klines[-1].close

        # Golden cross: fast crosses above slow
        if fast_prev <= slow_prev and fast_current > slow_current:
            confidence = self._crossover_confidence(fast_current, slow_current, current_price)
            return SignalResult(
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                indicators={
                    "sma_fast": round(fast_current, 2),
                    "sma_slow": round(slow_current, 2),
                    "fast_period": self._fast_period,
                    "slow_period": self._slow_period,
                    "crossover": "golden",
                },
                entry_price=current_price,
                stop_loss=current_price * (Decimal("1") - self._sl_pct),
                take_profit=current_price * (Decimal("1") + self._tp_pct),
            )

        # Death cross: fast crosses below slow
        if fast_prev >= slow_prev and fast_current < slow_current:
            confidence = self._crossover_confidence(fast_current, slow_current, current_price)
            return SignalResult(
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                indicators={
                    "sma_fast": round(fast_current, 2),
                    "sma_slow": round(slow_current, 2),
                    "fast_period": self._fast_period,
                    "slow_period": self._slow_period,
                    "crossover": "death",
                },
                entry_price=current_price,
                stop_loss=current_price * (Decimal("1") + self._sl_pct),
                take_profit=current_price * (Decimal("1") - self._tp_pct),
            )

        return None

    @staticmethod
    def _sma(values: list[float], period: int, offset: int = 0) -> float:
        """Calculate SMA. offset=0 is latest, offset=1 is one bar back."""
        end = len(values) - offset
        start = end - period
        if start < 0:
            return 0.0
        return sum(values[start:end]) / period

    @staticmethod
    def _crossover_confidence(fast: float, slow: float, price: Decimal) -> Decimal:
        """Confidence based on separation distance (normalized by price)."""
        if float(price) == 0:
            return Decimal("0.6")
        separation = abs(fast - slow) / float(price)
        # Map separation to confidence: 0% → 0.6, 1%+ → 0.85
        confidence = 0.6 + min(separation / 0.01, 1.0) * 0.25
        return Decimal(str(round(min(confidence, 0.85), 4)))
