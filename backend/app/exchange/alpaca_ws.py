"""Alpaca WebSocket for real-time US stock market data."""

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

from alpaca.data.live import StockDataStream

from app.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.exchange.base import PriceTick
from app.exchange.market_hours import is_us_market_open

logger = get_logger(__name__)

MAX_RECONNECT_DELAY = 60
MARKET_CHECK_INTERVAL = 60  # Check market hours every 60s


class AlpacaWebSocket:
    """Manages Alpaca WebSocket streams with market hours awareness."""

    def __init__(self):
        self._stream: StockDataStream | None = None
        self._running = False
        self._reconnect_delay = 1
        self._redis = get_redis()
        self._subscriptions: set[str] = set()
        self._callbacks: dict[str, list] = {}

    async def subscribe_ticker(self, symbol: str, callback=None) -> None:
        """Subscribe to real-time quotes for a stock symbol."""
        self._subscriptions.add(symbol)
        if callback:
            self._callbacks.setdefault(f"quote:{symbol}", []).append(callback)

    async def start(self) -> None:
        """Start the WebSocket connection with market hours awareness."""
        self._running = True
        while self._running:
            try:
                if not is_us_market_open():
                    logger.info("alpaca_ws_market_closed", waiting=True)
                    await self._redis.set("ws:stocks:connected", "0")
                    # Wait and check periodically
                    while self._running and not is_us_market_open():
                        await asyncio.sleep(MARKET_CHECK_INTERVAL)
                    if not self._running:
                        break

                await self._connect_and_listen()
            except Exception as e:
                if not self._running:
                    break

                try:
                    await self._redis.set("ws:stocks:connected", "0")
                except Exception:
                    pass

                logger.warning(
                    "alpaca_ws_disconnected",
                    error=str(e),
                    reconnect_delay=self._reconnect_delay,
                )

                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, MAX_RECONNECT_DELAY
                )

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._running = False
        if self._stream:
            await self._stream.close()
            self._stream = None
        logger.info("alpaca_ws_stopped")

    async def _connect_and_listen(self) -> None:
        if not self._subscriptions:
            logger.warning("alpaca_ws_no_subscriptions")
            await asyncio.sleep(5)
            return

        self._stream = StockDataStream(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_api_secret,
        )

        # Register quote handler
        async def on_quote(data):
            await self._handle_quote(data)

        for symbol in self._subscriptions:
            self._stream.subscribe_quotes(on_quote, symbol)

        self._reconnect_delay = 1
        await self._redis.set("ws:stocks:connected", "1")
        logger.info("alpaca_ws_connected", symbols=list(self._subscriptions))

        # _run_forever() is the async version; .run() is sync (calls asyncio.run)
        # which would block our event loop, so we use the internal async method
        await self._stream._run_forever()

    async def _handle_quote(self, data) -> None:
        """Handle incoming quote, cache in Redis."""
        symbol = data.symbol
        bid = Decimal(str(data.bid_price))
        ask = Decimal(str(data.ask_price))
        price = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)
        now = datetime.now(timezone.utc)

        tick = PriceTick(
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            timestamp=now,
        )

        # Cache in Redis (same format as Binance WS)
        cache_key = f"price:{symbol}"
        await self._redis.hset(cache_key, mapping={
            "price": str(tick.price),
            "bid": str(tick.bid),
            "ask": str(tick.ask),
            "timestamp": str(tick.timestamp.timestamp()),
        })
        await self._redis.expire(cache_key, 30)

        # Publish for subscribers
        await self._redis.publish(
            f"prices:{symbol}",
            json.dumps({
                "symbol": symbol,
                "price": str(tick.price),
                "bid": str(tick.bid),
                "ask": str(tick.ask),
                "timestamp": tick.timestamp.isoformat(),
            }),
        )

        # Fire callbacks
        for cb in self._callbacks.get(f"quote:{symbol}", []):
            try:
                await cb(tick)
            except Exception as e:
                logger.error("alpaca_ws_callback_error", error=str(e))
