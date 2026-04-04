"""Approval Executor — picks up approved orders and executes them.

When require_manual_approval=True, the pipeline creates orders
in PENDING_APPROVAL state. After human approves (→ SUBMITTED),
this worker detects them and completes execution.

Flow:
1. Poll for orders with status=SUBMITTED + no exchange_order_id (not yet executed)
2. Delegate to TradingPipeline.execute_approved_order() which handles:
   - Lock portfolio, re-check balance, guard validation
   - Submit to exchange, create position, update portfolio
"""
import asyncio
from decimal import Decimal

from sqlalchemy import select, and_

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.enums import OrderStatus
from app.models.order import Order
from app.models.risk_config import RiskConfig
from app.pipeline.capital_manager.capital_manager import CapitalManager
from app.pipeline.execution.base import BaseExecutor
from app.pipeline.execution.guard import ExecutionGuard, MarketSnapshot
from app.pipeline.orchestrator import TradingPipeline
from app.pipeline.risk_manager.risk_manager import RiskManager
from app.services.market_data import MarketDataService

logger = get_logger(__name__)

POLL_INTERVAL = 5  # seconds


class ApprovalExecutor:
    """Background worker: executes approved orders via TradingPipeline."""

    def __init__(
        self,
        executor: BaseExecutor,
        guard: ExecutionGuard,
        market_data: MarketDataService,
        session_factory,
        risk_manager: RiskManager | None = None,
        capital_manager: CapitalManager | None = None,
    ):
        self._executor = executor
        self._guard = guard
        self._market_data = market_data
        self._session_factory = session_factory
        self._risk_manager = risk_manager or RiskManager.create_default()
        self._capital_manager = capital_manager or CapitalManager()
        self._running = False
        self._redis = get_redis()

    async def _refresh_from_profile(self) -> None:
        """Reload risk manager and capital manager from active DB profile."""
        try:
            async with self._session_factory() as session:
                stmt = select(RiskConfig).where(RiskConfig.is_active == True)
                result = await session.execute(stmt)
                config = result.scalar_one_or_none()

            if config:
                self._risk_manager = RiskManager.create_default(
                    min_confidence=config.min_confidence,
                    max_positions=config.max_positions,
                    max_exposure_pct=config.max_exposure_per_symbol_pct,
                )
                self._capital_manager = CapitalManager(
                    risk_per_trade_pct=config.risk_per_trade_pct,
                    max_exposure_per_symbol_pct=config.max_exposure_per_symbol_pct,
                )
        except Exception as e:
            logger.error("approval_profile_refresh_failed", error=str(e))

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

        # Refresh pipeline components from active profile each cycle
        await self._refresh_from_profile()

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

    async def _execute_order(self, session, order: Order) -> None:
        """Execute a single approved order via the shared pipeline logic."""
        try:
            # Get market snapshot for guard validation
            snapshot = await self._market_data.get_market_snapshot(order.symbol)
            market = MarketSnapshot(
                symbol=order.symbol,
                price=snapshot["price"],
                bid=snapshot["bid"],
                ask=snapshot["ask"],
                volume_24h=snapshot["volume_24h"],
                asset_class=snapshot.get("asset_class", "CRYPTO"),
            )
        except Exception as e:
            logger.warning(
                "approval_market_data_failed",
                order_id=str(order.id),
                error=str(e),
            )
            order.status = OrderStatus.REJECTED.value
            return

        # Delegate to TradingPipeline's shared execution logic
        pipeline = TradingPipeline(
            risk_manager=self._risk_manager,
            capital_manager=self._capital_manager,
            execution_guard=self._guard,
            executor=self._executor,
            session=session,
        )

        result = await pipeline.execute_approved_order(order, market)

        logger.info(
            "approval_result",
            order_id=str(order.id),
            action=result.action,
            reason=result.reason,
        )
