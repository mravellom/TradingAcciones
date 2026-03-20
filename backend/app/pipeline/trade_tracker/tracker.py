from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import AggregateType, EventType
from app.repositories.event_repo import EventRepository

logger = get_logger(__name__)


class TradeTracker:
    """Records every pipeline decision as events for audit trail."""

    def __init__(self, session: AsyncSession):
        self._events = EventRepository(session)

    async def record_signal(
        self, signal_id: UUID, data: dict, correlation_id: str
    ) -> None:
        await self._events.append(
            aggregate_type=AggregateType.SIGNAL,
            aggregate_id=signal_id,
            event_type=EventType.SIGNAL_GENERATED,
            event_data=data,
            metadata={"correlation_id": correlation_id},
        )

    async def record_risk_approved(
        self, order_id: UUID, rules_passed: int, correlation_id: str
    ) -> None:
        await self._events.append(
            aggregate_type=AggregateType.ORDER,
            aggregate_id=order_id,
            event_type=EventType.RISK_APPROVED,
            event_data={"rules_passed": rules_passed},
            metadata={"correlation_id": correlation_id},
        )

    async def record_risk_rejected(
        self, order_id: UUID, rule: str, reason: str, correlation_id: str
    ) -> None:
        await self._events.append(
            aggregate_type=AggregateType.ORDER,
            aggregate_id=order_id,
            event_type=EventType.RISK_REJECTED,
            event_data={"rule": rule, "reason": reason},
            metadata={"correlation_id": correlation_id},
        )

    async def record_guard_approved(
        self, order_id: UUID, correlation_id: str
    ) -> None:
        await self._events.append(
            aggregate_type=AggregateType.ORDER,
            aggregate_id=order_id,
            event_type=EventType.GUARD_APPROVED,
            event_data={},
            metadata={"correlation_id": correlation_id},
        )

    async def record_guard_rejected(
        self, order_id: UUID, reason: str, correlation_id: str
    ) -> None:
        await self._events.append(
            aggregate_type=AggregateType.ORDER,
            aggregate_id=order_id,
            event_type=EventType.GUARD_REJECTED,
            event_data={"reason": reason},
            metadata={"correlation_id": correlation_id},
        )

    async def record_order_submitted(
        self, order_id: UUID, correlation_id: str
    ) -> None:
        await self._events.append(
            aggregate_type=AggregateType.ORDER,
            aggregate_id=order_id,
            event_type=EventType.ORDER_SUBMITTED,
            event_data={},
            metadata={"correlation_id": correlation_id},
        )

    async def record_order_filled(
        self, order_id: UUID, price: Decimal, quantity: Decimal,
        slippage: Decimal, correlation_id: str,
    ) -> None:
        await self._events.append(
            aggregate_type=AggregateType.ORDER,
            aggregate_id=order_id,
            event_type=EventType.ORDER_FILLED,
            event_data={
                "fill_price": str(price),
                "quantity": str(quantity),
                "slippage": str(slippage),
            },
            metadata={"correlation_id": correlation_id},
        )
