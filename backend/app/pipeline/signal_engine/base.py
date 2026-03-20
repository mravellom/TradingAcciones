from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domain.enums import SignalType
from app.exchange.base import Kline


@dataclass
class SignalResult:
    """Output of a signal generator."""

    symbol: str
    signal_type: SignalType
    confidence: Decimal
    indicators: dict = field(default_factory=dict)
    entry_price: Decimal = Decimal("0")
    stop_loss: Decimal = Decimal("0")
    take_profit: Decimal = Decimal("0")


class SignalGenerator(ABC):
    """Abstract base for signal generators (RSI, SMA, etc.)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of this generator."""

    @abstractmethod
    async def generate(self, symbol: str, klines: list[Kline]) -> SignalResult | None:
        """Analyze klines and return a signal, or None if no signal.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT")
            klines: OHLCV candle data, oldest first

        Returns:
            SignalResult if a signal is detected, None otherwise.
        """
