import asyncio
import time
from datetime import datetime, time as dt_time
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.enums import AssetClass, ExecutionMode, PositionStatus
from app.exchange.market_hours import is_us_market_open

ET = ZoneInfo("America/New_York")
MARKET_CLOSE_WARNING = dt_time(15, 55)  # 3:55 PM ET — 5 min before close
from app.pipeline.position_manager.position_manager import PositionManager
from app.repositories.position_repo import PositionRepository
from app.services.portfolio_service import PortfolioService

logger = get_logger(__name__)

DEFAULT_CHECK_INTERVAL = 2  # seconds
MAX_PRICE_STALE_SECONDS = 15  # reject prices older than this
CLOSE_DEDUP_TTL = 30  # Redis dedup key TTL
# Max acceptable spread for exit orders (per asset class)
EXIT_MAX_SPREAD_PCT_CRYPTO = Decimal("0.01")  # 1%
EXIT_MAX_SPREAD_PCT_STOCKS = Decimal("0.005")  # 0.5%


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
                is_stock = getattr(position, "asset_class", "CRYPTO") == AssetClass.STOCKS.value

                if is_stock:
                    # Auto-close stock positions near market close (3:55 PM ET)
                    now_et = datetime.now(ET)
                    if now_et.time() >= MARKET_CLOSE_WARNING and is_us_market_open():
                        current_price = await self._get_price(position.symbol)
                        if current_price:
                            logger.warning(
                                "market_close_auto_close",
                                position_id=str(position.id),
                                symbol=position.symbol,
                                price=str(current_price),
                            )
                            await self._close_triggered(
                                session, pos_mgr, portfolio_svc, position,
                                current_price, "MARKET_CLOSE",
                            )
                        continue

                    # Skip stock positions outside US market hours
                    if not is_us_market_open():
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

    async def _check_exit_spread(self, symbol: str, asset_class: str) -> str | None:
        """Check if spread is acceptable for closing. Returns warning or None."""
        cached = await self._redis.hgetall(f"price:{symbol}")
        if not cached or "bid" not in cached or "ask" not in cached:
            return None  # No spread data — allow close (safety first)

        try:
            bid = Decimal(cached["bid"])
            ask = Decimal(cached["ask"])
            if bid <= 0:
                return None
            spread = (ask - bid) / bid
            max_spread = (
                EXIT_MAX_SPREAD_PCT_STOCKS
                if asset_class == AssetClass.STOCKS.value
                else EXIT_MAX_SPREAD_PCT_CRYPTO
            )
            if spread > max_spread:
                return f"Exit spread {spread:.2%} exceeds max {max_spread:.2%}"
        except (ArithmeticError, ValueError):
            return None  # Unparseable data — allow close

        return None

    async def _close_triggered(
        self, session, pos_mgr, portfolio_svc, position,
        current_price: Decimal, reason: str,
    ) -> None:
        """Close a position with deduplication guard and spread check."""
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

        # Check spread before closing (skip for MARKET_CLOSE — must exit regardless)
        if reason != "MARKET_CLOSE":
            asset_class = getattr(position, "asset_class", "CRYPTO")
            spread_warning = await self._check_exit_spread(position.symbol, asset_class)
            if spread_warning:
                logger.warning(
                    "exit_spread_too_wide",
                    position_id=str(position.id),
                    symbol=position.symbol,
                    reason=reason,
                    detail=spread_warning,
                )
                # Release dedup key so next cycle can retry
                await self._redis.delete(dedup_key)
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
