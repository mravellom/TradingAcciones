"""Approval Executor — picks up approved orders and executes them.

When require_manual_approval=True, the pipeline creates orders
in PENDING_APPROVAL state. After human approves (→ SUBMITTED),
this worker detects them and completes execution.

Flow:
1. Poll for orders with status=SUBMITTED + no exchange_order_id (not yet executed)
2. Lock portfolio (SELECT FOR UPDATE)
3. Re-validate market conditions (guard)
4. Execute via paper/binance executor
5. Create position + update portfolio
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.enums import (
    ExecutionMode,
    OrderSide,
    OrderStatus,
)
from app.models.order import Order
from app.models.portfolio import Portfolio
from app.pipeline.execution.base import BaseExecutor
from app.pipeline.execution.guard import ExecutionGuard, MarketSnapshot
from app.pipeline.position_manager.position_manager import PositionManager
from app.pipeline.trade_tracker.tracker import TradeTracker
from app.services.market_data import MarketDataService

logger = get_logger(__name__)

POLL_INTERVAL = 5  # seconds


class ApprovalExecutor:
    """Background worker: executes approved orders."""

    def __init__(
        self,
        executor: BaseExecutor,
        guard: ExecutionGuard,
        market_data: MarketDataService,
        session_factory,
    ):
        self._executor = executor
        self._guard = guard
        self._market_data = market_data
        self._session_factory = session_factory
        self._running = False
        self._redis = get_redis()

    async def start(self) -> None:
        self._running = True
        logger.info("approval_executor_started")
        while self._running:
            try:
                await self._poll_cycle()
            except Exception as e:
                logger.error("approval_executor_error", error=str(e))
            await asyncio.sleep(POLL_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        logger.info("approval_executor_stopped")

    async def _poll_cycle(self) -> None:
        """Find approved orders and execute them."""
        # Check system status
        status = await self._redis.get("system:status") or "RUNNING"
        if status != "RUNNING":
            return

        async with self._session_factory() as session:
            # Find orders that were approved (SUBMITTED) but not yet executed
            stmt = (
                select(Order)
                .where(
                    and_(
                        Order.status == OrderStatus.SUBMITTED.value,
                        Order.exchange_order_id.is_(None),
                    )
                )
                .order_by(Order.created_at)
                .limit(5)
            )
            result = await session.execute(stmt)
            pending_orders = list(result.scalars().all())

            for order in pending_orders:
                await self._execute_order(session, order)

            if pending_orders:
                await session.commit()

    async def _execute_order(self, session: AsyncSession, order: Order) -> None:
        """Execute a single approved order."""
        try:
            # 1. Lock portfolio
            stmt = (
                select(Portfolio)
                .where(Portfolio.execution_mode == order.execution_mode)
                .with_for_update()
            )
            result = await session.execute(stmt)
            portfolio = result.scalar_one_or_none()

            if portfolio is None:
                logger.error("approval_no_portfolio", order_id=str(order.id))
                order.status = OrderStatus.REJECTED.value
                return

            # 2. Re-check balance
            fill_value = order.requested_qty * order.requested_price
            if portfolio.available_balance < fill_value:
                logger.warning(
                    "approval_insufficient_balance",
                    order_id=str(order.id),
                    available=str(portfolio.available_balance),
                    required=str(fill_value),
                )
                order.status = OrderStatus.REJECTED.value
                return

            # 3. Re-validate market (guard) — price may have moved since approval
            try:
                snapshot = await self._market_data.get_market_snapshot(order.symbol)
                market = MarketSnapshot(
                    symbol=order.symbol,
                    price=snapshot["price"],
                    bid=snapshot["bid"],
                    ask=snapshot["ask"],
                    volume_24h=snapshot["volume_24h"],
                )
                guard_result = await self._guard.validate(
                    order_price=order.requested_price,
                    order_quantity=order.requested_qty,
                    market=market,
                    side=order.side,
                )
                if not guard_result.approved:
                    logger.warning(
                        "approval_guard_rejected",
                        order_id=str(order.id),
                        reason=guard_result.reason,
                    )
                    order.status = OrderStatus.REJECTED.value
                    return
            except Exception as e:
                logger.warning(
                    "approval_guard_skipped",
                    order_id=str(order.id),
                    error=str(e),
                )
                # If market data unavailable, reject for safety
                order.status = OrderStatus.REJECTED.value
                return

            # 4. Execute
            fill = await self._executor.submit(
                order_id=order.id,
                symbol=order.symbol,
                side=OrderSide(order.side),
                quantity=order.requested_qty,
                price=order.requested_price,
            )

            # 5. Update order
            if fill.quantity >= order.requested_qty:
                order.status = OrderStatus.FILLED.value
            else:
                order.status = OrderStatus.PARTIALLY_FILLED.value

            order.filled_qty = fill.quantity
            order.avg_fill_price = fill.price
            order.exchange_order_id = fill.exchange_order_id

            # 6. Create position
            pos_mgr = PositionManager(session)
            position = await pos_mgr.open_position(
                fill=fill,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                strategy_id=order.signal_id,  # Link back to signal
                signal_confidence=Decimal("0.7"),  # TODO: store in order
                execution_mode=order.execution_mode,
            )

            # 7. Update portfolio (atomic SQL update)
            from app.services.portfolio_service import PortfolioService
            portfolio_svc = PortfolioService(session)
            actual_fill_value = fill.price * fill.quantity
            await portfolio_svc.record_fill(
                ExecutionMode(order.execution_mode), actual_fill_value
            )

            # 8. Record events
            tracker = TradeTracker(session)
            await tracker.record_order_filled(
                order.id, fill.price, fill.quantity, fill.slippage, ""
            )

            await session.flush()

            logger.info(
                "approval_executed",
                order_id=str(order.id),
                position_id=str(position.id),
                symbol=order.symbol,
                fill_price=str(fill.price),
                quantity=str(fill.quantity),
            )

            # Notify
            try:
                from app.core.notifications import notifier
                await notifier.notify_fill(
                    order.symbol, order.side, str(fill.quantity), str(fill.price)
                )
            except Exception as notif_err:
                logger.error("notification_failed", order_id=str(order.id), error=str(notif_err))

        except Exception as e:
            logger.error(
                "approval_execute_failed",
                order_id=str(order.id),
                error=str(e),
            )
            order.status = OrderStatus.REJECTED.value
