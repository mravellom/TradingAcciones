"""Daily reset task: resets daily PnL at UTC midnight.

Also expires stale pending approvals.
"""
import asyncio
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.domain.enums import ExecutionMode
from app.services.approval_service import ApprovalService
from app.services.portfolio_service import PortfolioService

logger = get_logger(__name__)


class DailyResetTask:
    """Runs at midnight UTC to reset daily metrics."""

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._running = False
        self._last_reset_date: str | None = None

    async def start(self) -> None:
        self._running = True
        logger.info("daily_reset_task_started")
        while self._running:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._last_reset_date != today:
                await self._do_reset()
                self._last_reset_date = today
            await asyncio.sleep(60)  # Check every minute

    async def stop(self) -> None:
        self._running = False

    async def _do_reset(self) -> None:
        async with self._session_factory() as session:
            # Reset daily PnL
            portfolio_svc = PortfolioService(session)
            await portfolio_svc.reset_daily_pnl(ExecutionMode.PAPER)
            await portfolio_svc.reset_daily_pnl(ExecutionMode.LIVE)

            # Expire stale approvals
            approval_svc = ApprovalService(session)
            expired = await approval_svc.expire_stale_approvals()

            await session.commit()

            logger.info(
                "daily_reset_complete",
                expired_approvals=expired,
            )
