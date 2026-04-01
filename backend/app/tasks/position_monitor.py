import asyncio
import time
from decimal import Decimal

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.enums import AssetClass, ExecutionMode, PositionStatus
from app.exchange.market_hours import is_us_market_open
from app.pipeline.position_manager.position_manager import PositionManager
from app.repositories.position_repo import PositionRepository
from app.services.portfolio_service import PortfolioService

logger = get_logger(__name__)

DEFAULT_CHECK_INTERVAL = 2  # seconds
MAX_PRICE_STALE_SECONDS = 15  # reject prices older than this
CLOSE_DEDUP_TTL = 30  # Redis dedup key TTL


class PositionMonitor:
    """Background task that monitors open positions for SL/TP triggers.

    Safety features:
    - Uses SELECT FOR UPDATE SKIP LOCKED to prevent duplicate closes
    - Validates price freshness before SL/TP decisions
    - Redis-based deduplication to prevent double closes across cycles
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
        self._stale_counters: dict[str, int] = {}

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

            # Use FOR UPDATE SKIP LOCKED to prevent concurrent cycles
            # from processing the same position
            open_positions = await repo.get_open_for_update()

            for position in open_positions:
                # Skip stock positions outside US market hours
                if (
                    getattr(position, "asset_class", "CRYPTO") == AssetClass.STOCKS.value
                    and not is_us_market_open()
                ):
                    continue

                current_price = await self._get_price(position.symbol)
                if current_price is None:
                    # Track stale price count for auto-halt
                    self._stale_counters[position.symbol] = (
                        self._stale_counters.get(position.symbol, 0) + 1
                    )
                    if self._stale_counters[position.symbol] >= 5:
                        logger.error(
                            "price_stale_threshold",
                            symbol=position.symbol,
                            consecutive_stale=self._stale_counters[position.symbol],
                        )
                        # Auto-halt to protect open positions
                        await self._redis.set("system:status", "HALTED")
                        try:
                            from app.core.notifications import notifier
                            await notifier.notify_system_halt(
                                f"Stale prices for {position.symbol} — auto-halted"
                            )
                        except Exception as notif_err:
                            logger.error("notification_failed", error=str(notif_err))
                    continue

                # Reset stale counter on fresh price
                self._stale_counters[position.symbol] = 0

                # Update position's current price
                await pos_mgr.update_price(position.id, current_price)

                # Check stop loss
                if await pos_mgr.check_stop_loss(position, current_price):
                    await self._close_triggered(
                        session, pos_mgr, portfolio_svc, position,
                        current_price, "STOP_LOSS",
                    )

                # Check take profit
                elif await pos_mgr.check_take_profit(position, current_price):
                    await self._close_triggered(
                        session, pos_mgr, portfolio_svc, position,
                        current_price, "TAKE_PROFIT",
                    )

            await session.commit()

    async def _close_triggered(
        self, session, pos_mgr, portfolio_svc, position,
        current_price: Decimal, reason: str,
    ) -> None:
        """Close a position with deduplication guard."""
        dedup_key = f"closing:{position.id}"

        # Deduplication: only one close per position within TTL window
        was_set = await self._redis.set(dedup_key, "1", nx=True, ex=CLOSE_DEDUP_TTL)
        if not was_set:
            logger.info(
                "close_dedup_skipped",
                position_id=str(position.id),
                reason=reason,
            )
            return

        log_fn = logger.warning if reason == "STOP_LOSS" else logger.info
        log_fn(
            f"{reason.lower()}_triggered",
            position_id=str(position.id),
            symbol=position.symbol,
            trigger_price=str(current_price),
        )

        trade = await pos_mgr.close_position(
            position_id=position.id,
            exit_price=current_price,
            reason=reason,
        )
        position_value = position.entry_price * position.quantity
        await portfolio_svc.record_close(
            ExecutionMode(position.execution_mode), position_value, trade.pnl
        )

        # Notify
        try:
            from app.core.notifications import notifier
            if reason == "STOP_LOSS":
                await notifier.notify_stop_loss(
                    position.symbol, str(position.entry_price),
                    str(current_price), str(trade.pnl),
                )
            else:
                await notifier.notify_take_profit(
                    position.symbol, str(position.entry_price),
                    str(current_price), str(trade.pnl),
                )
        except Exception as notif_err:
            logger.error("notification_failed", error=str(notif_err))

    async def _get_price(self, symbol: str) -> Decimal | None:
        """Get latest price from Redis cache with staleness validation."""
        cached = await self._redis.hgetall(f"price:{symbol}")
        if not cached or "price" not in cached:
            return None

        # Validate price freshness
        if "timestamp" in cached:
            try:
                price_ts = float(cached["timestamp"])
                age = time.time() - price_ts
                if age > MAX_PRICE_STALE_SECONDS:
                    logger.warning(
                        "price_stale",
                        symbol=symbol,
                        age_seconds=round(age, 1),
                        max_allowed=MAX_PRICE_STALE_SECONDS,
                    )
                    return None
            except (ValueError, TypeError):
                pass  # If timestamp is unparseable, accept price but log

        return Decimal(cached["price"])
