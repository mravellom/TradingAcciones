import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.dependencies import get_db_session
from app.domain.enums import ExecutionMode, PositionStatus
from app.pipeline.position_manager.position_manager import PositionManager
from app.repositories.position_repo import PositionRepository
from app.schemas.position import PositionResponse
from app.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("/", response_model=list[PositionResponse])
async def list_positions(
    asset_class: str | None = Query(None, pattern="^(CRYPTO|STOCKS)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    repo = PositionRepository(db)
    if asset_class:
        positions = await repo.get_by_asset_class(asset_class, limit=limit)
    else:
        positions = await repo.get_all(limit=limit)
    return positions


@router.get("/open", response_model=list[PositionResponse])
async def list_open_positions(db: AsyncSession = Depends(get_db_session)):
    repo = PositionRepository(db)
    return await repo.get_open()


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    repo = PositionRepository(db)
    position = await repo.get_by_id(position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return position


@router.post("/{position_id}/close")
async def close_position(
    position_id: uuid.UUID,
    exit_price: Decimal | None = None,
    reason: str = "MANUAL_CLOSE",
    db: AsyncSession = Depends(get_db_session),
    _auth: str = Depends(verify_api_key),
):
    """Manually close a position at current market price or specified price."""
    repo = PositionRepository(db)
    position = await repo.get_by_id(position_id)

    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")

    if position.status not in (PositionStatus.OPEN.value, PositionStatus.PARTIALLY_CLOSED.value):
        raise HTTPException(status_code=400, detail=f"Position is already {position.status}")

    # Use provided price or current price from position
    price = exit_price or position.current_price
    if price <= 0:
        raise HTTPException(status_code=400, detail="Invalid exit price")

    pos_mgr = PositionManager(db)
    try:
        trade = await pos_mgr.close_position(
            position_id=position_id,
            exit_price=price,
            reason=reason,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Update portfolio
    portfolio_svc = PortfolioService(db)
    position_value = position.entry_price * position.quantity
    await portfolio_svc.record_close(
        ExecutionMode(position.execution_mode),
        position_value,
        trade.pnl,
    )

    return {
        "status": "closed",
        "position_id": str(position_id),
        "exit_price": str(price),
        "pnl": str(trade.pnl),
        "pnl_percent": str(trade.pnl_percent),
    }
