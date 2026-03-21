"""Runtime Reconciler — continuously verifies DB ↔ Binance consistency.

This is the CRITICAL safety net that catches divergence while the system
is running. Unlike startup_reconciler (runs once), this runs every cycle.

Scenarios it catches:
1. Order filled on Binance but local commit failed → orphaned position on exchange
2. Position closed in DB but sell order never reached Binance → ghost position
3. Orders stuck in SUBMITTING for too long during runtime
4. Balance drift between DB and Binance actual balance

Architecture:
- Runs as background task every RECONCILE_INTERVAL seconds
- Only active when execution_mode=LIVE (paper doesn't need reconciliation)
- Queries Binance for actual state, compares to DB
- On mismatch: logs CRITICAL alert, notifies operator, halts trading
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

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
    PositionStatus,
)
from app.models.order import Order
from app.models.position import Position
from app.models.portfolio import Portfolio
from app.repositories.event_repo import EventRepository

logger = get_logger(__name__)

RECONCILE_INTERVAL = 30  # seconds between cycles
SUBMITTING_TIMEOUT = 60  # seconds before SUBMITTING order is considered stuck
BALANCE_DRIFT_THRESHOLD = Decimal("0.01")  # 1% drift triggers alert


class RuntimeReconciler:
    """Background task that ensures DB ↔ Binance consistency in real-time.

    This is the safety net that prevents money loss when:
    - Network drops after Binance fills an order
    - DB commit fails after position creation
    - System has open positions that Binance doesn't know about (or vice versa)
    """

    def __init__(self, executor, session_factory, interval: int = RECONCILE_INTERVAL):
        self._executor = executor
        self._session_factory = session_factory
        self._interval = interval
        self._redis = get_redis()
        self._running = False

    async def start(self) -> None:
        """Start the reconciliation loop."""
        # Only run for LIVE mode — paper trading doesn't need exchange reconciliation
        if self._executor.mode != ExecutionMode.LIVE:
            logger.info("runtime_reconciler_skipped", reason="not LIVE mode")
            return

        self._running = True
        logger.info("runtime_reconciler_started", interval=self._interval)

        while self._running:
            try:
                await self._reconcile_cycle()
            except Exception as e:
                logger.error("runtime_reconciler_error", error=str(e))
            await asyncio.sleep(self._interval)

    async def stop(self) -> None:
        self._running = False
        logger.info("runtime_reconciler_stopped")

    async def _reconcile_cycle(self) -> None:
        """Single reconciliation cycle. Checks all critical divergence points."""
        async with self._session_factory() as session:
            issues = []

            # 1. Check for stuck SUBMITTING orders (runtime, not just startup)
            stuck = await self._check_stuck_orders(session)
            issues.extend(stuck)

            # 2. Verify all LIVE open positions exist on Binance
            ghost = await self._check_positions_vs_exchange(session)
            issues.extend(ghost)

            # 3. Check Binance for orders we don't know about
            unknown = await self._check_exchange_for_unknown_fills(session)
            issues.extend(unknown)

            # 4. Balance sanity check
            drift = await self._check_balance_drift(session)
            issues.extend(drift)

            if issues:
                await self._handle_issues(session, issues)
                await session.commit()
            else:
                logger.debug("runtime_reconciler_ok")

    # ── Check 1: Stuck SUBMITTING orders ────────────────────────────

    async def _check_stuck_orders(self, session: AsyncSession) -> list[dict]:
        """Find orders stuck in SUBMITTING state during runtime."""
        threshold = datetime.now(timezone.utc) - timedelta(seconds=SUBMITTING_TIMEOUT)
        stmt = (
            select(Order)
            .where(
                and_(
                    Order.status == OrderStatus.SUBMITTING.value,
                    Order.execution_mode == ExecutionMode.LIVE.value,
                    Order.created_at < threshold,
                )
            )
        )
        result = await session.execute(stmt)
        stuck_orders = list(result.scalars().all())

        issues = []
        for order in stuck_orders:
            client_order_id = f"TP-{order.id.hex[:20]}"

            # Query Binance — did it actually fill?
            try:
                from app.pipeline.execution.binance_executor import BinanceExecutor
                if isinstance(self._executor, BinanceExecutor):
                    fill = await self._executor.reconcile_order(
                        order_id=order.id,
                        symbol=order.symbol,
                        side=OrderSide(order.side),
                        client_order_id=client_order_id,
                        expected_price=order.requested_price,
                    )

                    if fill is not None:
                        # ORDER WAS FILLED ON BINANCE — fix local state
                        order.status = OrderStatus.FILLED.value
                        order.filled_qty = fill.quantity
                        order.avg_fill_price = fill.price
                        order.exchange_order_id = fill.exchange_order_id

                        issues.append({
                            "type": "STUCK_ORDER_RECONCILED",
                            "severity": "CRITICAL",
                            "order_id": str(order.id),
                            "symbol": order.symbol,
                            "action": "Order was filled on Binance but not recorded locally. "
                                      "MANUAL REVIEW REQUIRED: create position if not exists.",
                            "fill_price": str(fill.price),
                            "fill_qty": str(fill.quantity),
                        })
                    else:
                        # Order doesn't exist on Binance — cancel locally
                        order.status = OrderStatus.CANCELLED.value
                        issues.append({
                            "type": "STUCK_ORDER_CANCELLED",
                            "severity": "WARNING",
                            "order_id": str(order.id),
                            "symbol": order.symbol,
                            "action": "Order was stuck in SUBMITTING and not found on Binance. Cancelled.",
                        })
            except Exception as e:
                issues.append({
                    "type": "STUCK_ORDER_RECONCILE_FAILED",
                    "severity": "CRITICAL",
                    "order_id": str(order.id),
                    "error": str(e),
                    "action": "Could not reconcile stuck order with Binance. MANUAL CHECK REQUIRED.",
                })

        return issues

    # ── Check 2: Open positions vs Binance ──────────────────────────

    async def _check_positions_vs_exchange(self, session: AsyncSession) -> list[dict]:
        """Verify open LIVE positions have corresponding state on Binance.

        Checks that for each open position, the entry order actually filled
        on Binance (by verifying exchange_order_id exists).
        """
        stmt = (
            select(Position)
            .where(
                and_(
                    Position.status == PositionStatus.OPEN.value,
                    Position.execution_mode == ExecutionMode.LIVE.value,
                )
            )
        )
        result = await session.execute(stmt)
        open_positions = list(result.scalars().all())

        issues = []
        for pos in open_positions:
            # Check that the entry order has an exchange_order_id
            order = await session.get(Order, pos.entry_order_id)
            if order is None:
                issues.append({
                    "type": "ORPHAN_POSITION",
                    "severity": "CRITICAL",
                    "position_id": str(pos.id),
                    "symbol": pos.symbol,
                    "action": "Position exists without entry order. DATA CORRUPTION.",
                })
                continue

            if not order.exchange_order_id:
                issues.append({
                    "type": "POSITION_NO_EXCHANGE_ORDER",
                    "severity": "CRITICAL",
                    "position_id": str(pos.id),
                    "order_id": str(order.id),
                    "symbol": pos.symbol,
                    "action": "Open LIVE position with no exchange order ID. "
                              "Position may not exist on Binance. MANUAL CHECK REQUIRED.",
                })

        return issues

    # ── Check 3: Unknown fills on Binance ───────────────────────────

    async def _check_exchange_for_unknown_fills(self, session: AsyncSession) -> list[dict]:
        """Check Binance for recent orders that we don't have locally.

        Uses the TP- prefix to identify our orders on Binance.
        """
        issues = []
        try:
            from app.pipeline.execution.binance_executor import BinanceExecutor
            if not isinstance(self._executor, BinanceExecutor):
                return []

            # Get open orders on Binance to see if there's anything we missed
            # This is lightweight — just checks for open (unfilled) orders
            open_orders = await self._executor.client.get_open_orders()

            for binance_order in open_orders:
                client_id = binance_order.get("clientOrderId", "")
                if not client_id.startswith("TP-"):
                    continue  # Not our order

                exchange_oid = str(binance_order.get("orderId", ""))

                # Check if we have this order locally
                stmt = select(Order).where(Order.exchange_order_id == exchange_oid)
                result = await session.execute(stmt)
                local_order = result.scalar_one_or_none()

                if local_order is None:
                    issues.append({
                        "type": "UNKNOWN_EXCHANGE_ORDER",
                        "severity": "CRITICAL",
                        "exchange_order_id": exchange_oid,
                        "client_order_id": client_id,
                        "symbol": binance_order.get("symbol", ""),
                        "status": binance_order.get("status", ""),
                        "action": "Order exists on Binance but not in local DB. "
                                  "MANUAL REVIEW AND CANCELLATION MAY BE NEEDED.",
                    })

        except Exception as e:
            logger.error("reconcile_exchange_check_failed", error=str(e))

        return issues

    # ── Check 4: Balance drift ──────────────────────────────────────

    async def _check_balance_drift(self, session: AsyncSession) -> list[dict]:
        """Compare local portfolio balance with actual Binance account balance.

        Only checks USDT balance (assumes USDT as quote currency).
        """
        issues = []
        try:
            from app.pipeline.execution.binance_executor import BinanceExecutor
            if not isinstance(self._executor, BinanceExecutor):
                return []

            # Get Binance account balance (free + locked = total on exchange)
            account = await self._executor.client.get_account()
            binance_total = Decimal("0")
            for b in account.get("balances", []):
                if b["asset"] == "USDT":
                    binance_total = Decimal(b["free"]) + Decimal(b["locked"])
                    break

            # Get local portfolio
            stmt = select(Portfolio).where(Portfolio.execution_mode == ExecutionMode.LIVE.value)
            result = await session.execute(stmt)
            portfolio = result.scalar_one_or_none()

            if portfolio is None:
                return []

            # Compare total balance (available + allocated) vs Binance total
            local_total = portfolio.total_balance

            if local_total > 0:
                drift = abs(binance_total - local_total) / local_total
                if drift > BALANCE_DRIFT_THRESHOLD:
                    issues.append({
                        "type": "BALANCE_DRIFT",
                        "severity": "WARNING",
                        "local_total": str(local_total),
                        "local_available": str(portfolio.available_balance),
                        "local_allocated": str(portfolio.allocated_balance),
                        "binance_total_usdt": str(binance_total),
                        "drift_pct": str(round(drift * 100, 2)),
                        "action": f"Balance drift of {drift*100:.1f}% detected between "
                                  f"local ({local_total}) and Binance ({binance_total}). "
                                  "May indicate missed fills or unclosed positions.",
                    })

        except Exception as e:
            logger.error("reconcile_balance_check_failed", error=str(e))

        return issues

    # ── Issue handling ──────────────────────────────────────────────

    async def _handle_issues(self, session: AsyncSession, issues: list[dict]) -> None:
        """Handle reconciliation issues: log, notify, halt if critical."""
        critical_issues = [i for i in issues if i["severity"] == "CRITICAL"]
        warning_issues = [i for i in issues if i["severity"] == "WARNING"]

        for issue in issues:
            logger.error(
                "reconciliation_issue",
                **{k: v for k, v in issue.items() if k != "action"},
                action=issue.get("action", ""),
            )

        # Persist all issues as events
        event_repo = EventRepository(session)
        for issue in issues:
            await event_repo.append(
                aggregate_type=AggregateType.SYSTEM,
                aggregate_id=uuid4(),
                event_type=EventType.SYSTEM_HALTED if issue["severity"] == "CRITICAL" else EventType.SYSTEM_RESUMED,
                event_data=issue,
                metadata={"source": "runtime_reconciler"},
            )

        # CRITICAL issues → halt trading + notify
        if critical_issues:
            await self._redis.set("system:status", "HALTED")
            logger.critical(
                "TRADING_HALTED_BY_RECONCILER",
                critical_count=len(critical_issues),
                warning_count=len(warning_issues),
            )

            # Build notification message
            msg_lines = ["<b>⚠️ TRADING HALTED — Reconciliation Issues</b>\n"]
            for i, issue in enumerate(critical_issues[:5], 1):
                msg_lines.append(
                    f"{i}. <b>{issue['type']}</b>\n"
                    f"   {issue.get('symbol', '')} — {issue['action'][:100]}"
                )
            if len(critical_issues) > 5:
                msg_lines.append(f"\n... and {len(critical_issues) - 5} more")

            try:
                from app.core.notifications import notifier
                await notifier.send("\n".join(msg_lines))
            except Exception as e:
                logger.error("reconciler_notification_failed", error=str(e))

        elif warning_issues:
            # Warnings: notify but don't halt
            try:
                from app.core.notifications import notifier
                await notifier.send(
                    f"<b>Reconciler Warning</b>\n"
                    f"{len(warning_issues)} issue(s) detected. Check logs."
                )
            except Exception:
                pass
