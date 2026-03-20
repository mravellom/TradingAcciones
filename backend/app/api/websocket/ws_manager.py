"""WebSocket connection manager.

Manages client connections, channel subscriptions, and bridges
Redis pub/sub events to connected WebSocket clients.
"""
import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)

# Available channels clients can subscribe to
VALID_CHANNELS = {
    "signals",
    "orders",
    "positions",
    "portfolio",
    "risk",
    "system",
}


class ConnectionManager:
    """Manages WebSocket connections and channel subscriptions."""

    def __init__(self):
        # channel -> set of websockets
        self._subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._connections: set[WebSocket] = set()
        self._redis_task: asyncio.Task | None = None

    async def connect(self, websocket: WebSocket, channels: list[str]) -> None:
        """Accept a WebSocket connection and subscribe to channels."""
        await websocket.accept()
        self._connections.add(websocket)

        for ch in channels:
            if ch in VALID_CHANNELS or ch.startswith("prices:"):
                self._subscriptions[ch].add(websocket)

        logger.info(
            "ws_connected",
            channels=channels,
            total_connections=len(self._connections),
        )

        # Start Redis listener if not running
        if self._redis_task is None or self._redis_task.done():
            self._redis_task = asyncio.create_task(self._redis_listener())

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket from all subscriptions."""
        self._connections.discard(websocket)
        for channel_subs in self._subscriptions.values():
            channel_subs.discard(websocket)
        logger.info("ws_disconnected", total_connections=len(self._connections))

    async def broadcast(self, channel: str, message: dict) -> None:
        """Send a message to all subscribers of a channel."""
        subscribers = self._subscriptions.get(channel, set())
        if not subscribers:
            return

        payload = json.dumps(message, default=str)
        dead = set()
        for ws in subscribers:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)

        # Clean up dead connections
        for ws in dead:
            await self.disconnect(ws)

    async def _redis_listener(self) -> None:
        """Subscribe to all Redis channels and forward to WebSocket clients."""
        redis = get_redis()
        pubsub = redis.pubsub()

        # Subscribe to all valid channels
        channels = list(VALID_CHANNELS)
        await pubsub.subscribe(*channels)

        logger.info("ws_redis_listener_started", channels=channels)

        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()

                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue

                await self.broadcast(channel, data)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("ws_redis_listener_error", error=str(e))
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
            logger.info("ws_redis_listener_stopped")

    async def shutdown(self) -> None:
        """Close all connections and stop Redis listener."""
        if self._redis_task and not self._redis_task.done():
            self._redis_task.cancel()

        for ws in list(self._connections):
            try:
                await ws.close()
            except Exception:
                pass
        self._connections.clear()
        self._subscriptions.clear()


# Singleton instance
manager = ConnectionManager()
