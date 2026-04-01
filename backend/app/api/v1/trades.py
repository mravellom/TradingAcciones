import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session
from app.repositories.trade_repo import TradeRepository
from app.schemas.trade import TradeResponse

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("/", response_model=list[TradeResponse])
async def list_trades(
    symbol: str | None = Query(None),
    asset_class: str | None = Query(None, pattern="^(CRYPTO|STOCKS)$"),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    repo = TradeRepository(db)
    if asset_class:
        trades = await repo.get_by_asset_class(asset_class, limit=limit)
    elif symbol:
        trades = await repo.get_by_symbol(symbol.upper(), limit=limit)
    else:
        trades = await repo.get_all(limit=limit)
    return trades


@router.get("/win-rate")
async def get_win_rate(
    strategy_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    repo = TradeRepository(db)
    rate = await repo.get_win_rate(strategy_id)
    return {"win_rate": round(rate, 4)}


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)):
    repo = TradeRepository(db)
    trade = await repo.get_by_id(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade
