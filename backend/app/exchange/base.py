from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class Ticker:
    symbol: str
    price: Decimal
    bid: Decimal
    ask: Decimal
    volume_24h: Decimal
    timestamp: datetime


@dataclass
class Kline:
    symbol: str
    interval: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time: datetime


@dataclass
class SymbolInfo:
    symbol: str
    base_asset: str       # BTC / AAPL
    quote_asset: str      # USDT / USD
    min_qty: Decimal
    max_qty: Decimal
    step_size: Decimal    # lot size increment
    min_notional: Decimal # minimum order value
    tick_size: Decimal    # price increment
    asset_class: str = "CRYPTO"


@dataclass
class PriceTick:
    """Real-time price tick from WebSocket feed."""
    symbol: str
    price: Decimal
    bid: Decimal
    ask: Decimal
    timestamp: datetime


class ExchangeClient(ABC):
    """Abstract exchange adapter. Implement for each exchange (Binance, Alpaca, etc.)."""

    @property
    def asset_class(self) -> str:
        return "CRYPTO"

    @abstractmethod
    async def connect(self) -> None:
        """Initialize connection to the exchange."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """Get current ticker for a symbol."""

    @abstractmethod
    async def get_klines(
        self, symbol: str, interval: str, limit: int = 100
    ) -> list[Kline]:
        """Get OHLCV candlestick data."""

    @abstractmethod
    async def get_exchange_info(self, symbol: str) -> SymbolInfo:
        """Get trading rules for a symbol."""

    @abstractmethod
    async def get_all_tickers(self) -> list[Ticker]:
        """Get tickers for all symbols."""

    @abstractmethod
    async def ping(self) -> float:
        """Ping exchange, return latency in ms."""
