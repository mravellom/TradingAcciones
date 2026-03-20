from decimal import Decimal
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.exchange.base import ExchangeClient, Kline, Ticker

logger = get_logger(__name__)


class MarketDataService:
    """Orchestrates market data fetching with caching."""

    def __init__(self, exchange: ExchangeClient):
        self._exchange = exchange
        self._redis = get_redis()

    async def get_ticker(self, symbol: str) -> Ticker:
        return await self._exchange.get_ticker(symbol)

    async def get_klines(
        self, symbol: str, interval: str, limit: int = 100
    ) -> list[Kline]:
        return await self._exchange.get_klines(symbol, interval, limit)

    async def get_current_price(self, symbol: str) -> Decimal:
        """Get the latest cached price, or fetch from exchange."""
        cached = await self._redis.hgetall(f"price:{symbol}")
        if cached and "price" in cached:
            return Decimal(cached["price"])

        ticker = await self._exchange.get_ticker(symbol)
        return ticker.price

    async def get_market_snapshot(self, symbol: str) -> dict:
        """Get a full market snapshot for Execution Guard."""
        ticker = await self._exchange.get_ticker(symbol)
        return {
            "symbol": symbol,
            "price": ticker.price,
            "bid": ticker.bid,
            "ask": ticker.ask,
            "volume_24h": ticker.volume_24h,
            "timestamp": ticker.timestamp,
        }
