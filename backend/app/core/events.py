"""Event publisher: publishes pipeline events to Redis pub/sub.

WebSocket manager subscribes to these channels and forwards to Angular clients.
This decouples the pipeline from client connections.
"""
import json
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)


class EventPublisher:
    """Publishes trading events to Redis pub/sub channels."""

    def __init__(self):
        self._redis = get_redis()

    async def publish(self, channel: str, event: str, data: dict) -> None:
        """Publish an event to a Redis channel."""
        message = {
            "channel": channel,
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.publish(channel, json.dumps(message, default=str))

    # ── Convenience methods ──

    async def signal_generated(self, signal_data: dict) -> None:
        await self.publish("signals", "signal_generated", signal_data)

    async def order_updated(self, order_data: dict) -> None:
        await self.publish("orders", "order_updated", order_data)

    async def position_updated(self, position_data: dict) -> None:
        await self.publish("positions", "position_updated", position_data)

    async def position_closed(self, trade_data: dict) -> None:
        await self.publish("positions", "position_closed", trade_data)

    async def portfolio_updated(self, portfolio_data: dict) -> None:
        await self.publish("portfolio", "portfolio_updated", portfolio_data)

    async def risk_alert(self, alert_data: dict) -> None:
        await self.publish("risk", "risk_alert", alert_data)

    async def system_status(self, status: str, reason: str = "") -> None:
        await self.publish("system", "system_status", {
            "status": status,
            "reason": reason,
        })

    async def price_update(self, symbol: str, price_data: dict) -> None:
        await self.publish(f"prices:{symbol}", "price_update", price_data)
