import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.dependencies import get_db_session
from app.models.strategy_config import StrategyConfig
from app.schemas.strategy import (
    StrategyConfigCreate,
    StrategyConfigResponse,
    StrategyConfigUpdate,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("/", response_model=list[StrategyConfigResponse])
async def list_strategies(db: AsyncSession = Depends(get_db_session)):
    stmt = select(StrategyConfig).order_by(StrategyConfig.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/", response_model=StrategyConfigResponse, status_code=201)
async def create_strategy(
    data: StrategyConfigCreate,
    db: AsyncSession = Depends(get_db_session),
    _auth: str = Depends(verify_api_key),
):
    strategy = StrategyConfig(
        name=data.name,
        description=data.description,
        strategy_type=data.strategy_type,
        parameters=data.parameters,
        symbols=data.symbols,
        timeframe=data.timeframe,
    )
    db.add(strategy)
    await db.flush()
    return strategy


@router.get("/{strategy_id}", response_model=StrategyConfigResponse)
async def get_strategy(
    strategy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    strategy = await db.get(StrategyConfig, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@router.put("/{strategy_id}", response_model=StrategyConfigResponse)
async def update_strategy(
    strategy_id: uuid.UUID,
    data: StrategyConfigUpdate,
    db: AsyncSession = Depends(get_db_session),
    _auth: str = Depends(verify_api_key),
):
    strategy = await db.get(StrategyConfig, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(strategy, field, value)

    if "parameters" in update_data or "symbols" in update_data or "timeframe" in update_data:
        strategy.version += 1

    await db.flush()
    return strategy


@router.post("/{strategy_id}/activate", response_model=StrategyConfigResponse)
async def activate_strategy(
    strategy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    _auth: str = Depends(verify_api_key),
):
    strategy = await db.get(StrategyConfig, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy.is_active = True
    await db.flush()
    return strategy


@router.post("/{strategy_id}/deactivate", response_model=StrategyConfigResponse)
async def deactivate_strategy(
    strategy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    _auth: str = Depends(verify_api_key),
):
    strategy = await db.get(StrategyConfig, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy.is_active = False
    await db.flush()
    return strategy
