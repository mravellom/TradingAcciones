from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session
from app.domain.enums import ExecutionMode
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
