"""Startup Reconciler — recovers orphaned orders and system state.

Runs once during application startup to:
1. Reconcile orders stuck in SUBMITTING state with Binance
2. Recover circuit breaker state from DB event store
3. Clean up stale Redis system status
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.enums import (
    AggregateType,
    EventType,
    ExecutionMode,
    OrderSide,
    OrderStatus,
)
from app.models.event_store import EventStore
from app.models.order import Order
from app.pipeline.execution.base import BaseExecutor

logger = get_logger(__name__)

# Orders older than this in SUBMITTING state are considered orphaned
ORPHAN_THRESHOLD_MINUTES = 5


async def reconcile(session: AsyncSession, executor: BaseExecutor | None = None) -> None:
    """Run all reconciliation checks on startup."""
    logger.info("startup_reconciler_started")

    await _clean_redis_status()
    await _recover_circuit_breaker(session)
    await _reconcile_orphaned_orders(session, executor)

    logger.info("startup_reconciler_completed")


async def _clean_redis_status() -> None:
    """Reset stale Redis system status from previous shutdown."""
    redis = get_redis()
    status = await redis.get("system:status")
    if status in ("SHUTTING_DOWN", None):
        await redis.set("system:status", "RUNNING")
        logger.info("redis_status_cleaned", old_status=status)


async def _recover_circuit_breaker(session: AsyncSession) -> None:
    """Check DB event store for unresolved circuit breaker activations."""
    redis = get_redis()

    # Find most recent CB event
    stmt = (
        select(EventStore)
        .where(
            EventStore.event_type.in_([
                EventType.CIRCUIT_BREAKER_ACTIVATED.value,
                EventType.CIRCUIT_BREAKER_RESET.value,
            ])
        )
        .order_by(EventStore.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    last_event = result.scalar_one_or_none()

    if last_event and last_event.event_type == EventType.CIRCUIT_BREAKER_ACTIVATED.value:
        # CB was activated but never reset — re-activate in Redis
        await redis.set("circuit_breaker:active", "1")
        reason = (last_event.event_data or {}).get("reason", "recovered from DB")
        await redis.set("circuit_breaker:reason", reason)
        logger.warning(
            "circuit_breaker_recovered",
            reason=reason,
            activated_at=str(last_event.created_at),
        )
    else:
        # CB was reset or never activated — ensure Redis is clean
        cb_active = await redis.get("circuit_breaker:active")
        if cb_active == "1":
            # Redis says active but DB says it was reset — trust DB
            await redis.delete("circuit_breaker:active")
            await redis.delete("circuit_breaker:reason")
            await redis.delete("circuit_breaker:activated_at")
            logger.info("circuit_breaker_redis_cleaned")


async def _reconcile_orphaned_orders(
    session: AsyncSession, executor: BaseExecutor | None
) -> None:
    """Find orders stuck in SUBMITTING state and reconcile with exchange."""
    threshold = datetime.now(timezone.utc) - timedelta(minutes=ORPHAN_THRESHOLD_MINUTES)

    stmt = (
        select(Order)
        .where(
            and_(
                Order.status == OrderStatus.SUBMITTING.value,
                Order.created_at < threshold,
            )
        )
        .order_by(Order.created_at)
    )
    result = await session.execute(stmt)
    orphaned = list(result.scalars().all())

    if not orphaned:
        logger.info("no_orphaned_orders")
        return

    logger.warning("orphaned_orders_found", count=len(orphaned))

    for order in orphaned:
        await _reconcile_single_order(session, order, executor)

    await session.flush()


async def _reconcile_single_order(
    session: AsyncSession, order: Order, executor: BaseExecutor | None
) -> None:
    """Reconcile a single orphaned order with the exchange."""
    client_order_id = f"TP-{order.id.hex[:20]}"

    # If we have a live executor, try to query Binance
    if executor is not None and order.execution_mode == ExecutionMode.LIVE.value:
        try:
            from app.pipeline.execution.binance_executor import BinanceExecutor
            if isinstance(executor, BinanceExecutor):
                fill = await executor.reconcile_order(
                    order_id=order.id,
                    symbol=order.symbol,
                    side=OrderSide(order.side),
                    client_order_id=client_order_id,
                    expected_price=order.requested_price,
                )
                if fill is not None:
                    # Order was actually filled on Binance
                    order.status = OrderStatus.FILLED.value
                    order.filled_qty = fill.quantity
                    order.avg_fill_price = fill.price
                    order.exchange_order_id = fill.exchange_order_id
                    logger.info(
                        "orphaned_order_reconciled_as_filled",
                        order_id=str(order.id),
                        exchange_order_id=fill.exchange_order_id,
                    )
                    # Note: position creation is NOT done here to avoid complexity.
                    # Operator should review reconciled orders manually.
                    return
        except Exception as e:
            logger.error(
                "orphaned_reconcile_error",
                order_id=str(order.id),
                error=str(e),
            )

    # If not reconciled, mark as CANCELLED
    order.status = OrderStatus.CANCELLED.value
    logger.info(
        "orphaned_order_cancelled",
        order_id=str(order.id),
        symbol=order.symbol,
    )
