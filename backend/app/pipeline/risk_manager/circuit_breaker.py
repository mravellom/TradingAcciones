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

    async def activate(self, reason: str, session=None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._redis.set(CIRCUIT_BREAKER_KEY, "1")
        await self._redis.set(CIRCUIT_BREAKER_REASON_KEY, reason)
        await self._redis.set(CIRCUIT_BREAKER_TIME_KEY, now)
        logger.warning("circuit_breaker_activated", reason=reason, activated_at=now)

        # Persist to DB event store for recovery after Redis restart
        if session is not None:
            try:
                from app.domain.enums import AggregateType, EventType
                from app.repositories.event_repo import EventRepository
                from uuid import uuid4
                event_repo = EventRepository(session)
                await event_repo.append(
                    aggregate_type=AggregateType.SYSTEM,
                    aggregate_id=uuid4(),
                    event_type=EventType.CIRCUIT_BREAKER_ACTIVATED,
                    event_data={"reason": reason, "activated_at": now},
                )
                await session.flush()
            except Exception as e:
                logger.error("cb_db_persist_failed", error=str(e))

    async def reset(self, session=None) -> None:
        reason = await self._redis.get(CIRCUIT_BREAKER_REASON_KEY) or "unknown"
        await self._redis.delete(
            CIRCUIT_BREAKER_KEY, CIRCUIT_BREAKER_REASON_KEY, CIRCUIT_BREAKER_TIME_KEY
        )
        logger.info("circuit_breaker_reset", previous_reason=reason)

        # Persist reset to DB
        if session is not None:
            try:
                from app.domain.enums import AggregateType, EventType
                from app.repositories.event_repo import EventRepository
                from uuid import uuid4
                event_repo = EventRepository(session)
                await event_repo.append(
                    aggregate_type=AggregateType.SYSTEM,
                    aggregate_id=uuid4(),
                    event_type=EventType.CIRCUIT_BREAKER_RESET,
                    event_data={"previous_reason": reason},
                )
                await session.flush()
            except Exception as e:
                logger.error("cb_reset_db_persist_failed", error=str(e))

    async def get_status(self) -> dict:
        active = await self.is_active()
        reason = await self._redis.get(CIRCUIT_BREAKER_REASON_KEY) or ""
        activated_at = await self._redis.get(CIRCUIT_BREAKER_TIME_KEY) or ""
        return {
            "active": active,
            "reason": reason,
            "activated_at": activated_at,
        }
