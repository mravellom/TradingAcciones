"""Signal Executor — picks up generated signals and runs them through the pipeline.

Polls the DB for unprocessed signals (no linked order, not expired)
and feeds them into TradingPipeline.execute() to create orders and positions.

Flow:
1. Poll for signals where expires_at > now AND no order references this signal
2. Convert Signal → TradeIntent
3. Get MarketSnapshot for the symbol
4. Build TradingPipeline and call execute(intent, market)
5. Log result (EXECUTED, REJECTED, etc.)
"""
import asyncio
from decimal import Decimal

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.enums import AssetClass, ExecutionMode, SignalType
from app.models.order import Order
from app.models.risk_config import RiskConfig
from app.models.signal import Signal
from app.pipeline.capital_manager.capital_manager import CapitalManager
from app.pipeline.execution.base import BaseExecutor
from app.pipeline.execution.guard import ExecutionGuard, MarketSnapshot
from app.pipeline.orchestrator import TradingPipeline
from app.pipeline.position_manager.position_manager import PositionManager
from app.pipeline.risk_manager.risk_manager import RiskManager
from app.pipeline.strategy.base import TradeIntent
from app.services.market_data import MarketDataService
from app.services.portfolio_service import PortfolioService

logger = get_logger(__name__)

POLL_INTERVAL = 10  # seconds


class SignalExecutor:
    """Background worker: converts signals into trades via the pipeline."""

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
        logger.info("signal_executor_started", interval=POLL_INTERVAL)
        while self._running:
            try:
                await self._poll_cycle()
            except Exception as e:
                logger.error("signal_executor_error", error=str(e))
            await asyncio.sleep(POLL_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        logger.info("signal_executor_stopped")

    async def _load_pipeline_config(self) -> tuple[RiskManager, CapitalManager]:
        """Load risk manager and capital manager from active DB profile."""
        async with self._session_factory() as session:
            stmt = select(RiskConfig).where(RiskConfig.is_active == True)
            result = await session.execute(stmt)
            config = result.scalar_one_or_none()

        if config:
            risk_mgr = RiskManager.create_default(
                min_confidence=config.min_confidence,
                max_positions=config.max_positions,
                max_exposure_pct=config.max_exposure_per_symbol_pct,
            )
            capital_mgr = CapitalManager(
                risk_per_trade_pct=config.risk_per_trade_pct,
                max_exposure_per_symbol_pct=config.max_exposure_per_symbol_pct,
            )
        else:
            risk_mgr = RiskManager.create_default()
            capital_mgr = CapitalManager()

        return risk_mgr, capital_mgr

    async def _poll_cycle(self) -> None:
        """Find unprocessed signals and execute them."""
        status = await self._redis.get("system:status") or "RUNNING"
        if status != "RUNNING":
            return

        from datetime import datetime, timezone

        async with self._session_factory() as session:
            # Find BUY and SELL signals that have no linked order and haven't expired.
            order_subq = select(Order.signal_id).where(Order.signal_id.isnot(None)).scalar_subquery()
            stmt = (
                select(Signal)
                .where(
                    and_(
                        Signal.signal_type.in_(["BUY", "SELL"]),
                        Signal.expires_at > datetime.now(timezone.utc),
                        Signal.id.notin_(order_subq),
                    )
                )
                .order_by(Signal.created_at)
                .limit(5)
            )
            result = await session.execute(stmt)
            pending_signals = list(result.scalars().all())

        if not pending_signals:
            return

        # Load pipeline config once per cycle
        risk_mgr, capital_mgr = await self._load_pipeline_config()

        for signal in pending_signals:
            if signal.signal_type == "SELL":
                await self._execute_sell_signal(signal)
            else:
                await self._execute_signal(signal, risk_mgr, capital_mgr)

    async def _execute_signal(
        self,
        signal: Signal,
        risk_mgr: RiskManager,
        capital_mgr: CapitalManager,
    ) -> None:
        """Convert a signal to a TradeIntent and run through the pipeline."""
        try:
            # Build TradeIntent from signal
            intent = TradeIntent(
                symbol=signal.symbol,
                action=SignalType(signal.signal_type),
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                confidence=signal.confidence,
                strategy_id=signal.strategy_id,
                indicators=signal.indicators or {},
                timeframe=signal.timeframe or "1h",
            )

            # Get market snapshot
            try:
                snapshot = await self._market_data.get_market_snapshot(signal.symbol)
                market = MarketSnapshot(
                    symbol=signal.symbol,
                    price=snapshot["price"],
                    bid=snapshot["bid"],
                    ask=snapshot["ask"],
                    volume_24h=snapshot["volume_24h"],
                    asset_class=snapshot.get("asset_class", "CRYPTO"),
                )
            except Exception as e:
                logger.warning(
                    "signal_executor_market_data_failed",
                    signal_id=str(signal.id),
                    symbol=signal.symbol,
                    error=str(e),
                )
                return

            # Execute through pipeline
            async with self._session_factory() as session:
                pipeline = TradingPipeline(
                    risk_manager=risk_mgr,
                    capital_manager=capital_mgr,
                    execution_guard=self._guard,
                    executor=self._executor,
                    session=session,
                )

                pipeline_result = await pipeline.execute(intent, market)

                # Commit the transaction — the orchestrator only flushes,
                # expecting the caller to commit (see orchestrator.py line 101).
                await session.commit()

                logger.info(
                    "signal_executor_result",
                    signal_id=str(signal.id),
                    symbol=signal.symbol,
                    signal_type=signal.signal_type,
                    action=pipeline_result.action,
                    reason=pipeline_result.reason,
                    order_id=str(pipeline_result.order_id) if pipeline_result.order_id else None,
                    position_id=str(pipeline_result.position_id) if pipeline_result.position_id else None,
                )

        except Exception as e:
            logger.error(
                "signal_executor_failed",
                signal_id=str(signal.id),
                symbol=signal.symbol,
                error=str(e),
            )

    async def _execute_sell_signal(self, signal: Signal) -> None:
        """Close open LONG positions for the symbol when a SELL signal arrives."""
        try:
            async with self._session_factory() as session:
                pos_mgr = PositionManager(session)
                portfolio_svc = PortfolioService(session)

                open_positions = await pos_mgr.get_open_by_symbol(signal.symbol)
                if not open_positions:
                    logger.info(
                        "sell_signal_no_positions",
                        signal_id=str(signal.id),
                        symbol=signal.symbol,
                    )
                    return

                # Get current market price for exit
                try:
                    snapshot = await self._market_data.get_market_snapshot(signal.symbol)
                    exit_price = snapshot["price"]
                except Exception as e:
                    logger.warning(
                        "sell_signal_market_data_failed",
                        signal_id=str(signal.id),
                        symbol=signal.symbol,
                        error=str(e),
                    )
                    return

                for position in open_positions:
                    trade = await pos_mgr.close_position(
                        position_id=position.id,
                        exit_price=exit_price,
                        reason="SELL_SIGNAL",
                    )
                    position_value = position.entry_price * position.quantity
                    await portfolio_svc.record_close(
                        ExecutionMode(position.execution_mode),
                        position_value,
                        trade.pnl,
                    )
                    logger.info(
                        "sell_signal_closed_position",
                        signal_id=str(signal.id),
                        position_id=str(position.id),
                        symbol=signal.symbol,
                        pnl=str(trade.pnl),
                    )

                await session.commit()

        except Exception as e:
            logger.error(
                "sell_signal_execution_failed",
                signal_id=str(signal.id),
                symbol=signal.symbol,
                error=str(e),
            )
