"""Trading Pipeline Orchestrator.

All database operations execute within a single transaction.
Portfolio reads use SELECT FOR UPDATE to prevent race conditions.
SL/TP are validated before execution.
Partial fills are handled correctly.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.enums import (
    AggregateType,
    AssetClass,
    EventType,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    RiskAction,
    SignalType,
)
from app.models.order import Order
from app.models.portfolio import Portfolio
from app.models.signal import Signal as SignalModel
from app.pipeline.capital_manager.capital_manager import CapitalManager
from app.pipeline.execution.base import BaseExecutor
from app.pipeline.execution.guard import ExecutionGuard, MarketSnapshot
from app.pipeline.position_manager.position_manager import PositionManager
from app.pipeline.risk_manager.risk_manager import RiskManager
from app.pipeline.risk_manager.rules.base import RiskContext
from app.pipeline.strategy.base import TradeIntent
from app.pipeline.trade_tracker.tracker import TradeTracker
from app.repositories.event_repo import EventRepository
from app.repositories.position_repo import PositionRepository
from app.services.portfolio_service import PortfolioService

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    action: str  # EXECUTED, REJECTED, GUARD_REJECTED, SYSTEM_HALTED, HOLD, ERROR
    reason: str = ""
    order_id: UUID | None = None
    position_id: UUID | None = None
    details: dict = field(default_factory=dict)


def _validate_sl_tp(intent: TradeIntent) -> str | None:
    """Validate SL/TP are logical for the trade direction.

    Returns error message if invalid, None if OK.
    """
    # Check positivity FIRST
    if intent.entry_price <= 0 or intent.stop_loss <= 0 or intent.take_profit <= 0:
        return "Prices must be positive"

    if intent.action == SignalType.BUY:
        if intent.stop_loss >= intent.entry_price:
            return f"BUY: stop_loss ({intent.stop_loss}) must be below entry ({intent.entry_price})"
        if intent.take_profit <= intent.entry_price:
            return f"BUY: take_profit ({intent.take_profit}) must be above entry ({intent.entry_price})"
    elif intent.action == SignalType.SELL:
        if intent.stop_loss <= intent.entry_price:
            return f"SELL: stop_loss ({intent.stop_loss}) must be above entry ({intent.entry_price})"
        if intent.take_profit >= intent.entry_price:
            return f"SELL: take_profit ({intent.take_profit}) must be below entry ({intent.entry_price})"

    return None


class TradingPipeline:
    """Orchestrates the full trading pipeline.

    Flow:
    0. Validate SL/TP
    1. Check system status
    2. Lock portfolio (SELECT FOR UPDATE)
    3. Risk Manager validates
    4. Capital Manager sizes
    5. Verify sufficient balance
    6. Execution Guard validates market conditions
    7. Executor fills order
    8. Handle fill (full or partial)
    9. Position Manager creates position
    10. Update portfolio atomically
    11. Trade Tracker records everything

    All DB operations happen in a single transaction (caller commits).
    """

    def __init__(
        self,
        risk_manager: RiskManager,
        capital_manager: CapitalManager,
        execution_guard: ExecutionGuard,
        executor: BaseExecutor,
        session: AsyncSession,
    ):
        self._risk = risk_manager
        self._capital = capital_manager
        self._guard = execution_guard
        self._executor = executor
        self._session = session
        self._redis = get_redis()
        self._position_mgr = PositionManager(session)
        self._tracker = TradeTracker(session)
        self._event_repo = EventRepository(session)
        self._position_repo = PositionRepository(session)

    async def execute(
        self,
        intent: TradeIntent,
        market: MarketSnapshot,
    ) -> PipelineResult:
        """Execute the full trading pipeline for a trade intent."""

        correlation_id = uuid4().hex

        # 0. Validate SL/TP
        sl_tp_error = _validate_sl_tp(intent)
        if sl_tp_error:
            return PipelineResult(action="REJECTED", reason=f"Invalid SL/TP: {sl_tp_error}")

        # 1. Check system status
        system_status = await self._redis.get("system:status") or "RUNNING"
        if system_status != "RUNNING":
            return PipelineResult(action="SYSTEM_HALTED", reason=f"System is {system_status}")

        try:
            # 2. Lock portfolio (SELECT FOR UPDATE prevents race conditions)
            portfolio = await self._lock_portfolio()
            if portfolio is None:
                return PipelineResult(action="ERROR", reason="No portfolio found")

            # Read position counts AFTER acquiring lock
            open_count = await self._position_repo.count_open()
            symbol_exposure = await self._position_repo.get_total_exposure_by_symbol(
                intent.symbol
            )

            # 3. Risk Manager
            risk_ctx = RiskContext(
                symbol=intent.symbol,
                signal_type=intent.action.value,
                confidence=intent.confidence,
                entry_price=intent.entry_price,
                stop_loss=intent.stop_loss,
                take_profit=intent.take_profit,
                strategy_id=str(intent.strategy_id),
                total_balance=portfolio.total_balance,
                available_balance=portfolio.available_balance,
                daily_pnl=portfolio.daily_pnl,
                max_drawdown=portfolio.max_drawdown,
                open_positions_count=open_count,
                symbol_exposure=symbol_exposure,
            )

            risk_decision = await self._risk.validate(risk_ctx)

            if risk_decision.action == RiskAction.HALT_SYSTEM:
                await self._event_repo.append(
                    aggregate_type=AggregateType.SYSTEM,
                    aggregate_id=uuid4(),
                    event_type=EventType.SYSTEM_HALTED,
                    event_data={"rule": risk_decision.rule, "reason": risk_decision.reason},
                    metadata={"correlation_id": correlation_id},
                )
                return PipelineResult(action="SYSTEM_HALTED", reason=risk_decision.reason)

            if risk_decision.action == RiskAction.REJECT:
                await self._tracker.record_risk_rejected(
                    uuid4(), risk_decision.rule, risk_decision.reason, correlation_id
                )
                return PipelineResult(
                    action="REJECTED",
                    reason=f"[{risk_decision.rule}] {risk_decision.reason}",
                )

            # 4. Capital Manager
            sizing = self._capital.calculate_size(
                entry_price=intent.entry_price,
                stop_loss=intent.stop_loss,
                confidence=intent.confidence,
                total_balance=portfolio.total_balance,
                available_balance=portfolio.available_balance,
                symbol_exposure=symbol_exposure,
            )

            if sizing is None:
                return PipelineResult(
                    action="REJECTED",
                    reason="Capital manager: position too small or impossible",
                )

            # 5. Verify sufficient balance BEFORE execution
            fill_value = sizing.quantity * intent.entry_price
            if portfolio.available_balance < fill_value:
                return PipelineResult(
                    action="REJECTED",
                    reason=f"Insufficient balance: available={portfolio.available_balance}, required={fill_value}",
                )

            # 6. Execution Guard
            guard_result = await self._guard.validate(
                order_price=intent.entry_price,
                order_quantity=sizing.quantity,
                market=market,
                side=intent.action.value,
            )

            if not guard_result.approved:
                await self._tracker.record_guard_rejected(
                    uuid4(), guard_result.reason, correlation_id
                )
                return PipelineResult(action="GUARD_REJECTED", reason=guard_result.reason)

            quantity = guard_result.adjusted_quantity or sizing.quantity

            # 7. Create signal + order records
            asset_class = (
                AssetClass.STOCKS.value
                if intent.symbol in settings.stock_symbols
                else AssetClass.CRYPTO.value
            )
            signal = SignalModel(
                symbol=intent.symbol,
                asset_class=asset_class,
                signal_type=intent.action.value,
                confidence=intent.confidence,
                timeframe=intent.timeframe,
                indicators=intent.indicators,
                entry_price=intent.entry_price,
                stop_loss=intent.stop_loss,
                take_profit=intent.take_profit,
                strategy_id=intent.strategy_id,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            self._session.add(signal)
            await self._session.flush()

            # Determine initial order status based on manual approval mode
            from app.config import settings
            if settings.require_manual_approval:
                initial_status = OrderStatus.PENDING_APPROVAL.value
            else:
                initial_status = OrderStatus.SUBMITTED.value

            order = Order(
                signal_id=signal.id,
                symbol=intent.symbol,
                asset_class=asset_class,
                side=OrderSide.BUY.value if intent.action.value == "BUY" else OrderSide.SELL.value,
                order_type="MARKET",
                status=initial_status,
                requested_qty=quantity,
                requested_price=intent.entry_price,
                stop_loss=intent.stop_loss,
                take_profit=intent.take_profit,
                execution_mode=self._executor.mode.value,
                risk_decision={
                    "action": risk_decision.action.value,
                    "rules_passed": len(self._risk._rules),
                },
                capital_decision={
                    "quantity": str(sizing.quantity),
                    "risk_amount": str(sizing.risk_amount),
                    "position_value": str(sizing.position_value),
                },
            )
            self._session.add(order)
            await self._session.flush()

            await self._tracker.record_risk_approved(
                order.id, len(self._risk._rules), correlation_id
            )
            await self._tracker.record_guard_approved(order.id, correlation_id)

            # If manual approval required, stop here and wait for human
            if settings.require_manual_approval:
                await self._session.flush()
                logger.info(
                    "pipeline_pending_approval",
                    order_id=str(order.id),
                    symbol=intent.symbol,
                    quantity=str(quantity),
                )
                # Notify via Telegram if configured
                try:
                    from app.core.notifications import notifier
                    await notifier.notify_pending_approval(
                        str(order.id), intent.symbol, intent.action.value,
                        str(quantity), str(intent.entry_price),
                    )
                except Exception as notif_err:
                    logger.error("notification_failed", order_id=str(order.id), error=str(notif_err))

                return PipelineResult(
                    action="PENDING_APPROVAL",
                    order_id=order.id,
                    reason="Waiting for manual approval",
                    details={
                        "quantity": str(quantity),
                        "entry_price": str(intent.entry_price),
                        "correlation_id": correlation_id,
                    },
                )

            await self._tracker.record_order_submitted(order.id, correlation_id)

            # 8. Persist SUBMITTING state to DISK before sending to exchange.
            # This is a real commit (not just flush) so it survives crashes.
            # If the process crashes after Binance accepts but before the final commit,
            # the startup/runtime reconciler will find this SUBMITTING order and reconcile.
            order.status = OrderStatus.SUBMITTING.value
            await self._session.commit()

            fill = await self._executor.submit(
                order_id=order.id,
                symbol=intent.symbol,
                side=OrderSide(order.side),
                quantity=quantity,
                price=intent.entry_price,
            )

            # 9. Handle fill (full or partial)
            if fill.quantity >= quantity:
                order.status = OrderStatus.FILLED.value
            else:
                order.status = OrderStatus.PARTIALLY_FILLED.value
                logger.warning(
                    "partial_fill",
                    order_id=str(order.id),
                    requested=str(quantity),
                    filled=str(fill.quantity),
                )

            order.filled_qty = fill.quantity
            order.avg_fill_price = fill.price
            order.exchange_order_id = fill.exchange_order_id

            await self._tracker.record_order_filled(
                order.id, fill.price, fill.quantity, fill.slippage, correlation_id
            )

            # 10. Create position (use ACTUAL fill qty, not requested)
            position = await self._position_mgr.open_position(
                fill=fill,
                stop_loss=intent.stop_loss,
                take_profit=intent.take_profit,
                strategy_id=intent.strategy_id,
                signal_confidence=intent.confidence,
                execution_mode=self._executor.mode.value,
                asset_class=asset_class,
            )

            # 10b. Place exchange-level SL/TP for LIVE mode
            if self._executor.mode == ExecutionMode.LIVE:
                try:
                    from app.pipeline.execution.binance_executor import BinanceExecutor
                    if isinstance(self._executor, BinanceExecutor):
                        oco_id = await self._executor.place_oco_order(
                            symbol=intent.symbol,
                            quantity=fill.quantity,
                            stop_loss=intent.stop_loss,
                            take_profit=intent.take_profit,
                        )
                        if oco_id:
                            position.oco_order_id = oco_id
                            await self._session.flush()
                except Exception as oco_err:
                    logger.error(
                        "oco_placement_failed",
                        position_id=str(position.id),
                        error=str(oco_err),
                    )

            # 11. Update portfolio atomically via SQL UPDATE
            # already_locked=True because we hold the FOR UPDATE lock from step 2
            actual_fill_value = fill.price * fill.quantity
            portfolio_svc = PortfolioService(self._session)
            await portfolio_svc.record_fill(
                ExecutionMode(self._executor.mode.value), actual_fill_value,
                already_locked=True,
            )

            await self._session.flush()

            logger.info(
                "pipeline_executed",
                order_id=str(order.id),
                position_id=str(position.id),
                symbol=intent.symbol,
                fill_price=str(fill.price),
                quantity=str(fill.quantity),
                correlation_id=correlation_id,
            )

            # Notify via Telegram
            try:
                from app.core.notifications import notifier
                await notifier.notify_fill(
                    symbol=intent.symbol,
                    side=order.side,
                    qty=str(fill.quantity),
                    price=str(fill.price),
                )
            except Exception:
                pass  # Never let notification failure break the pipeline

            return PipelineResult(
                action="EXECUTED",
                order_id=order.id,
                position_id=position.id,
                details={
                    "fill_price": str(fill.price),
                    "quantity": str(fill.quantity),
                    "slippage": str(fill.slippage),
                    "risk_amount": str(sizing.risk_amount),
                    "correlation_id": correlation_id,
                },
            )

        except Exception as e:
            logger.error(
                "pipeline_error",
                error=str(e),
                symbol=intent.symbol,
                correlation_id=correlation_id,
            )
            return PipelineResult(action="ERROR", reason=str(e))

    async def _lock_portfolio(self) -> Portfolio | None:
        """Acquire row-level lock on portfolio."""
        mode = self._executor.mode.value
        stmt = (
            select(Portfolio)
            .where(Portfolio.execution_mode == mode)
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
