import asyncio
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.enums import ExecutionMode, PositionStatus
from app.pipeline.position_manager.position_manager import PositionManager
from app.repositories.position_repo import PositionRepository
from app.services.portfolio_service import PortfolioService

logger = get_logger(__name__)

DEFAULT_CHECK_INTERVAL = 2  # seconds


class PositionMonitor:
    """Background task that monitors open positions for SL/TP triggers.

    Checks each tick (from Redis price cache) against open positions.
    When SL or TP is hit, closes the position automatically.
    """

    def __init__(
        self,
        session_factory,
        execution_mode: ExecutionMode = ExecutionMode.PAPER,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
    ):
        self._session_factory = session_factory
        self._execution_mode = execution_mode
        self._check_interval = check_interval
        self._redis = get_redis()
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("position_monitor_started", interval=self._check_interval)
        while self._running:
            try:
                await self._check_cycle()
            except Exception as e:
                logger.error("position_monitor_error", error=str(e))
            await asyncio.sleep(self._check_interval)

    async def stop(self) -> None:
        self._running = False
        logger.info("position_monitor_stopped")

    async def _check_cycle(self) -> None:
        """Check all open positions against current prices."""
        async with self._session_factory() as session:
            repo = PositionRepository(session)
            pos_mgr = PositionManager(session)
            portfolio_svc = PortfolioService(session)

            open_positions = await repo.get_open()

            for position in open_positions:
                current_price = await self._get_price(position.symbol)
                if current_price is None:
                    continue

                # Update position's current price
                await pos_mgr.update_price(position.id, current_price)

                # Check stop loss
                if await pos_mgr.check_stop_loss(position, current_price):
                    logger.warning(
                        "stop_loss_triggered",
                        position_id=str(position.id),
                        symbol=position.symbol,
                        sl=str(position.stop_loss),
                        price=str(current_price),
                    )
                    trade = await pos_mgr.close_position(
                        position_id=position.id,
                        exit_price=current_price,
                        reason="STOP_LOSS",
                    )
                    position_value = position.entry_price * position.quantity
                    await portfolio_svc.record_close(
                        self._execution_mode, position_value, trade.pnl
                    )

                # Check take profit
                elif await pos_mgr.check_take_profit(position, current_price):
                    logger.info(
                        "take_profit_triggered",
                        position_id=str(position.id),
                        symbol=position.symbol,
                        tp=str(position.take_profit),
                        price=str(current_price),
                    )
                    trade = await pos_mgr.close_position(
                        position_id=position.id,
                        exit_price=current_price,
                        reason="TAKE_PROFIT",
                    )
                    position_value = position.entry_price * position.quantity
                    await portfolio_svc.record_close(
                        self._execution_mode, position_value, trade.pnl
                    )

            await session.commit()

    async def _get_price(self, symbol: str) -> Decimal | None:
        """Get latest price from Redis cache."""
        cached = await self._redis.hgetall(f"price:{symbol}")
        if cached and "price" in cached:
            return Decimal(cached["price"])
        return None
