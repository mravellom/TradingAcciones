"""Human-in-the-loop approval service.

When require_manual_approval is enabled, orders go to PENDING_APPROVAL
and wait for human action via the API or Telegram before executing.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.events import EventPublisher
from app.core.logging import get_logger
from app.domain.enums import OrderStatus
from app.domain.state_machine import validate_order_transition
from app.models.order import Order

logger = get_logger(__name__)


class ApprovalService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._publisher = EventPublisher()

    async def get_pending_approvals(self) -> list[Order]:
        """Get all orders waiting for human approval."""
        stmt = (
            select(Order)
            .where(Order.status == OrderStatus.PENDING_APPROVAL.value)
            .order_by(Order.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def approve(self, order_id: uuid.UUID) -> Order:
        """Human approves an order for execution."""
        order = await self._session.get(Order, order_id)
        if order is None:
            raise ValueError(f"Order {order_id} not found")

        validate_order_transition(order.status, OrderStatus.SUBMITTED)
        order.status = OrderStatus.SUBMITTED.value
        await self._session.flush()

        logger.info("order_approved", order_id=str(order_id), symbol=order.symbol)

        await self._publisher.publish("orders", "order_approved", {
            "order_id": str(order_id),
            "symbol": order.symbol,
            "side": order.side,
            "quantity": str(order.requested_qty),
        })

        return order

    async def reject(self, order_id: uuid.UUID, reason: str = "Manually rejected") -> Order:
        """Human rejects an order."""
        order = await self._session.get(Order, order_id)
        if order is None:
            raise ValueError(f"Order {order_id} not found")

        validate_order_transition(order.status, OrderStatus.REJECTED)
        order.status = OrderStatus.REJECTED.value
        await self._session.flush()

        logger.info("order_rejected_manual", order_id=str(order_id), reason=reason)

        await self._publisher.publish("orders", "order_rejected", {
            "order_id": str(order_id),
            "reason": reason,
        })

        return order

    async def expire_stale_approvals(self) -> int:
        """Expire orders that have been PENDING_APPROVAL too long."""
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=settings.approval_timeout_seconds
        )
        stmt = select(Order).where(
            Order.status == OrderStatus.PENDING_APPROVAL.value,
            Order.created_at < cutoff,
        )
        result = await self._session.execute(stmt)
        expired = list(result.scalars().all())

        for order in expired:
            order.status = OrderStatus.EXPIRED.value
            logger.info("order_approval_expired", order_id=str(order.id))

        if expired:
            await self._session.flush()

        return len(expired)
