from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session
from app.domain.enums import ExecutionMode, PositionStatus
from app.models.position import Position
from app.models.trade import Trade
from app.repositories.portfolio_repo import PortfolioRepository
from app.schemas.portfolio import PortfolioResponse

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/", response_model=PortfolioResponse)
async def get_portfolio(
    mode: str = "PAPER",
    db: AsyncSession = Depends(get_db_session),
):
    repo = PortfolioRepository(db)
    portfolio = await repo.get_by_mode(ExecutionMode(mode))
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


@router.get("/breakdown")
async def get_portfolio_breakdown(
    mode: str = "PAPER",
    db: AsyncSession = Depends(get_db_session),
):
    """Get portfolio breakdown by asset class (crypto vs stocks)."""
    result = {}
    for asset_class in ("CRYPTO", "STOCKS"):
        # Open positions allocated
        alloc_stmt = select(
            func.coalesce(func.sum(Position.entry_price * Position.quantity), 0)
        ).where(
            Position.status == PositionStatus.OPEN.value,
            Position.execution_mode == mode,
            Position.asset_class == asset_class,
        )
        alloc_result = await db.execute(alloc_stmt)
        allocated = alloc_result.scalar_one()

        # Open positions count
        count_stmt = select(func.count()).where(
            Position.status == PositionStatus.OPEN.value,
            Position.execution_mode == mode,
            Position.asset_class == asset_class,
        )
        count_result = await db.execute(count_stmt)
        open_count = count_result.scalar_one()

        # Realized PnL
        pnl_stmt = select(
            func.coalesce(func.sum(Trade.pnl), 0)
        ).where(
            Trade.execution_mode == mode,
            Trade.asset_class == asset_class,
        )
        pnl_result = await db.execute(pnl_stmt)
        realized_pnl = pnl_result.scalar_one()

        # Unrealized PnL
        unreal_stmt = select(
            func.coalesce(func.sum(Position.unrealized_pnl), 0)
        ).where(
            Position.status == PositionStatus.OPEN.value,
            Position.execution_mode == mode,
            Position.asset_class == asset_class,
        )
        unreal_result = await db.execute(unreal_stmt)
        unrealized_pnl = unreal_result.scalar_one()

        result[asset_class] = {
            "allocated": str(allocated),
            "open_positions": open_count,
            "realized_pnl": str(realized_pnl),
            "unrealized_pnl": str(unrealized_pnl),
        }

    return result
