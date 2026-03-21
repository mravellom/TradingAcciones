import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import websockets

from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
BINANCE_TESTNET_WS_URL = "wss://testnet.binance.vision/ws"

MAX_RECONNECT_DELAY = 60  # seconds


@dataclass
class PriceTick:
    symbol: str
    price: Decimal
    bid: Decimal
    ask: Decimal
    timestamp: datetime


class BinanceWebSocket:
    """Manages Binance WebSocket streams with automatic reconnection."""

    def __init__(self, testnet: bool = True):
        self._base_url = BINANCE_TESTNET_WS_URL if testnet else BINANCE_WS_URL
        self._ws = None
        self._running = False
        self._reconnect_delay = 1
        self._redis = get_redis()
        self._subscriptions: set[str] = set()
        self._callbacks: dict[str, list] = {}

    async def subscribe_ticker(self, symbol: str, callback=None) -> None:
        """Subscribe to real-time ticker for a symbol."""
        stream = f"{symbol.lower()}@bookTicker"
        self._subscriptions.add(stream)
        if callback:
            self._callbacks.setdefault(stream, []).append(callback)

    async def subscribe_kline(self, symbol: str, interval: str, callback=None) -> None:
        """Subscribe to kline/candlestick stream."""
        stream = f"{symbol.lower()}@kline_{interval}"
        self._subscriptions.add(stream)
        if callback:
            self._callbacks.setdefault(stream, []).append(callback)

    async def start(self) -> None:
        """Start the WebSocket connection and message loop."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                if not self._running:
                    break

                # Mark as disconnected in Redis
                try:
                    await self._redis.set("ws:connected", "0")
                except Exception:
                    pass

                logger.warning(
                    "binance_ws_disconnected",
                    error=str(e),
                    reconnect_delay=self._reconnect_delay,
                )

                # Send notification at max delay threshold
                if self._reconnect_delay >= MAX_RECONNECT_DELAY:
                    try:
                        from app.core.notifications import notifier
                        await notifier.notify_system_halt(
                            f"Binance WebSocket disconnected for extended period. Error: {str(e)[:100]}"
                        )
                    except Exception:
                        pass

                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, MAX_RECONNECT_DELAY
                )

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("binance_ws_stopped")

    async def _connect_and_listen(self) -> None:
        streams = "/".join(self._subscriptions)
        if not streams:
            logger.warning("binance_ws_no_subscriptions")
            await asyncio.sleep(5)
            return

        url = f"{self._base_url}/{streams}"
        logger.info("binance_ws_connecting", url=url)

        async with websockets.connect(url, ping_interval=20) as ws:
            self._ws = ws
            self._reconnect_delay = 1  # Reset on successful connect
            # Mark as connected in Redis
            await self._redis.set("ws:connected", "1")
            logger.info("binance_ws_connected", streams=list(self._subscriptions))

            async for raw_msg in ws:
                if not self._running:
                    break
                await self._handle_message(raw_msg)

    async def _handle_message(self, raw_msg: str) -> None:
        try:
            data = json.loads(raw_msg)
        except json.JSONDecodeError:
            logger.warning("binance_ws_invalid_json", raw=raw_msg[:200])
            return

        event_type = data.get("e")

        if event_type == "bookTicker":
            tick = PriceTick(
                symbol=data["s"],
                price=Decimal(data["a"]),  # best ask as "price"
                bid=Decimal(data["b"]),
                ask=Decimal(data["a"]),
                timestamp=datetime.now(timezone.utc),
            )
            # Update Redis cache
            await self._cache_tick(tick)
            # Fire callbacks
            stream = f"{data['s'].lower()}@bookTicker"
            for cb in self._callbacks.get(stream, []):
                try:
                    await cb(tick)
                except Exception as e:
                    logger.error("binance_ws_callback_error", error=str(e))

        elif event_type == "kline":
            kline_data = data["k"]
            stream = f"{data['s'].lower()}@kline_{kline_data['i']}"
            for cb in self._callbacks.get(stream, []):
                try:
                    await cb(kline_data)
                except Exception as e:
                    logger.error("binance_ws_callback_error", error=str(e))

    async def _cache_tick(self, tick: PriceTick) -> None:
        """Cache latest price in Redis for fast access."""
        cache_key = f"price:{tick.symbol}"
        await self._redis.hset(cache_key, mapping={
            "price": str(tick.price),
            "bid": str(tick.bid),
            "ask": str(tick.ask),
            "timestamp": str(tick.timestamp.timestamp()),  # epoch seconds for staleness check
        })
        await self._redis.expire(cache_key, 30)

        # Publish for subscribers (WebSocket manager, position monitor)
        await self._redis.publish(
            f"prices:{tick.symbol}",
            json.dumps({
                "symbol": tick.symbol,
                "price": str(tick.price),
                "bid": str(tick.bid),
                "ask": str(tick.ask),
                "timestamp": tick.timestamp.isoformat(),
            }),
        )

    async def price_stream(self, symbol: str) -> AsyncIterator[PriceTick]:
        """Async iterator for price ticks of a symbol. Uses Redis pub/sub."""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(f"prices:{symbol}")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    yield PriceTick(
                        symbol=data["symbol"],
                        price=Decimal(data["price"]),
                        bid=Decimal(data["bid"]),
                        ask=Decimal(data["ask"]),
                        timestamp=datetime.fromisoformat(data["timestamp"]),
                    )
        finally:
            await pubsub.unsubscribe(f"prices:{symbol}")
            await pubsub.aclose()
