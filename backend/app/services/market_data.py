from decimal import Decimal
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.exchange.base import ExchangeClient, Kline, Ticker

logger = get_logger(__name__)


class MarketDataService:
    """Orchestrates market data fetching with caching and multi-exchange routing."""

    def __init__(
        self,
        exchange: ExchangeClient,
        stock_exchange: ExchangeClient | None = None,
    ):
        self._exchange = exchange
        self._stock_exchange = stock_exchange
        self._redis = get_redis()
        self._stock_symbols: set[str] = set()
        # Lazy-load stock symbols from config
        try:
            from app.config import settings
            if settings.alpaca_enabled:
                self._stock_symbols = set(settings.stock_symbols)
        except Exception:
            pass

    def _get_exchange(self, symbol: str) -> ExchangeClient:
        """Route to correct exchange based on symbol."""
        if self._stock_exchange and symbol in self._stock_symbols:
            return self._stock_exchange
        return self._exchange

    async def get_ticker(self, symbol: str) -> Ticker:
        return await self._get_exchange(symbol).get_ticker(symbol)

    async def get_klines(
        self, symbol: str, interval: str, limit: int = 100
    ) -> list[Kline]:
        return await self._get_exchange(symbol).get_klines(symbol, interval, limit)

    async def get_current_price(self, symbol: str) -> Decimal:
        """Get the latest cached price, or fetch from exchange."""
        cached = await self._redis.hgetall(f"price:{symbol}")
        if cached and "price" in cached:
            return Decimal(cached["price"])

        ticker = await self._get_exchange(symbol).get_ticker(symbol)
        return ticker.price

    async def get_market_snapshot(self, symbol: str) -> dict:
        """Get a full market snapshot for Execution Guard."""
        ticker = await self._get_exchange(symbol).get_ticker(symbol)
        asset_class = "STOCKS" if symbol in self._stock_symbols else "CRYPTO"
        return {
            "symbol": symbol,
            "price": ticker.price,
            "bid": ticker.bid,
            "ask": ticker.ask,
            "volume_24h": ticker.volume_24h,
            "timestamp": ticker.timestamp,
            "asset_class": asset_class,
        }
