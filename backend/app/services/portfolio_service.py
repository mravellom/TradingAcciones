"""Portfolio management with atomic balance updates.

All balance mutations use SELECT FOR UPDATE to prevent race conditions.
"""
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import ExecutionMode
from app.models.portfolio import Portfolio
from app.repositories.portfolio_repo import PortfolioRepository

logger = get_logger(__name__)


class PortfolioService:
    """Manages portfolio state: balances, PnL, drawdown."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = PortfolioRepository(session)

    async def get_or_create(self, mode: ExecutionMode, initial_balance: Decimal) -> Portfolio:
        """Get existing portfolio or create one."""
        portfolio = await self._repo.get_by_mode(mode)
        if portfolio is None:
            portfolio = Portfolio(
                execution_mode=mode.value,
                total_balance=initial_balance,
                available_balance=initial_balance,
                allocated_balance=Decimal("0"),
                total_pnl=Decimal("0"),
                daily_pnl=Decimal("0"),
                max_drawdown=Decimal("0"),
            )
            await self._repo.create(portfolio)
            logger.info("portfolio_created", mode=mode.value, balance=str(initial_balance))
        return portfolio

    async def _lock_portfolio(self, mode: ExecutionMode) -> Portfolio | None:
        """Get portfolio with row-level lock (SELECT FOR UPDATE)."""
        stmt = (
            select(Portfolio)
            .where(Portfolio.execution_mode == mode.value)
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def record_fill(
        self,
        mode: ExecutionMode,
        fill_value: Decimal,
    ) -> None:
        """Update portfolio after a fill. Uses atomic SQL UPDATE."""
        portfolio = await self._lock_portfolio(mode)
        if portfolio is None:
            raise ValueError(f"Portfolio not found for mode {mode.value}")

        if portfolio.available_balance < fill_value:
            raise ValueError(
                f"Insufficient balance: available={portfolio.available_balance}, "
                f"required={fill_value}"
            )

        # Atomic SQL update — prevents race conditions on balance
        stmt = (
            update(Portfolio)
            .where(Portfolio.id == portfolio.id)
            .values(
                available_balance=Portfolio.available_balance - fill_value,
                allocated_balance=Portfolio.allocated_balance + fill_value,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
        # Refresh to get updated values
        await self._session.refresh(portfolio)

    async def record_close(
        self,
        mode: ExecutionMode,
        position_value: Decimal,
        pnl: Decimal,
    ) -> None:
        """Update portfolio after closing a position. Uses atomic SQL UPDATE."""
        portfolio = await self._lock_portfolio(mode)
        if portfolio is None:
            raise ValueError(f"Portfolio not found for mode {mode.value}")

        # Atomic SQL update — all balance changes in a single statement
        new_available = Portfolio.available_balance + position_value + pnl
        new_allocated = Portfolio.allocated_balance - position_value
        stmt = (
            update(Portfolio)
            .where(Portfolio.id == portfolio.id)
            .values(
                allocated_balance=new_allocated,
                available_balance=new_available,
                total_pnl=Portfolio.total_pnl + pnl,
                daily_pnl=Portfolio.daily_pnl + pnl,
                total_balance=new_available + new_allocated,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
        # Refresh to get updated values for drawdown check
        await self._session.refresh(portfolio)

        # Update max drawdown (needs refreshed values)
        if portfolio.total_pnl < 0 and portfolio.total_balance > 0:
            initial_balance = portfolio.total_balance - portfolio.total_pnl
            current_dd = abs(portfolio.total_pnl) / initial_balance
            if current_dd > portfolio.max_drawdown:
                stmt_dd = (
                    update(Portfolio)
                    .where(Portfolio.id == portfolio.id)
                    .values(max_drawdown=current_dd)
                )
                await self._session.execute(stmt_dd)
                await self._session.flush()

        logger.info(
            "portfolio_updated",
            mode=mode.value,
            pnl=str(pnl),
            total_balance=str(portfolio.total_balance),
            available=str(portfolio.available_balance),
            allocated=str(portfolio.allocated_balance),
            daily_pnl=str(portfolio.daily_pnl),
        )

    async def reset_daily_pnl(self, mode: ExecutionMode) -> None:
        """Reset daily PnL. Called at start of each trading day."""
        portfolio = await self._lock_portfolio(mode)
        if portfolio:
            portfolio.daily_pnl = Decimal("0")
            await self._session.flush()
            logger.info("daily_pnl_reset", mode=mode.value)
