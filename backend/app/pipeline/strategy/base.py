from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.enums import SignalType
from app.exchange.base import Kline


@dataclass
class TradeIntent:
    """Output of strategy evaluation. Represents intent to trade."""

    symbol: str
    action: SignalType  # BUY / SELL / HOLD
    confidence: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    strategy_id: UUID
    timeframe: str
    indicators: dict


class Strategy(ABC):
    """Abstract base strategy. Evaluates market data and produces trade intents."""

    @property
    @abstractmethod
    def id(self) -> UUID:
        """Unique strategy ID."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name."""

    @abstractmethod
    async def evaluate(
        self, symbol: str, klines: list[Kline], timeframe: str
    ) -> TradeIntent | None:
        """Evaluate market data and return a trade intent, or None.

        Args:
            symbol: Trading pair
            klines: OHLCV data, oldest first
            timeframe: Candle interval ("1h", "4h", etc.)

        Returns:
            TradeIntent if the strategy sees an opportunity, None otherwise.
        """
