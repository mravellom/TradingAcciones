from datetime import datetime, timezone

from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)

CIRCUIT_BREAKER_KEY = "circuit_breaker:active"
CIRCUIT_BREAKER_REASON_KEY = "circuit_breaker:reason"
CIRCUIT_BREAKER_TIME_KEY = "circuit_breaker:activated_at"


class CircuitBreaker:
    """Emergency stop for the trading system.

    When activated, blocks ALL new orders until manually reset.
    Uses Redis for state so it survives restarts.
    """

    def __init__(self):
        self._redis = get_redis()

    async def is_active(self) -> bool:
        val = await self._redis.get(CIRCUIT_BREAKER_KEY)
        return val == "1"

    async def activate(self, reason: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._redis.set(CIRCUIT_BREAKER_KEY, "1")
        await self._redis.set(CIRCUIT_BREAKER_REASON_KEY, reason)
        await self._redis.set(CIRCUIT_BREAKER_TIME_KEY, now)
        logger.warning("circuit_breaker_activated", reason=reason, activated_at=now)

    async def reset(self) -> None:
        reason = await self._redis.get(CIRCUIT_BREAKER_REASON_KEY) or "unknown"
        await self._redis.delete(
            CIRCUIT_BREAKER_KEY, CIRCUIT_BREAKER_REASON_KEY, CIRCUIT_BREAKER_TIME_KEY
        )
        logger.info("circuit_breaker_reset", previous_reason=reason)

    async def get_status(self) -> dict:
        active = await self.is_active()
        reason = await self._redis.get(CIRCUIT_BREAKER_REASON_KEY) or ""
        activated_at = await self._redis.get(CIRCUIT_BREAKER_TIME_KEY) or ""
        return {
            "active": active,
            "reason": reason,
            "activated_at": activated_at,
        }
