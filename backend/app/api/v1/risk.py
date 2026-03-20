from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session, get_redis_client
from app.domain.enums import PositionStatus
from app.models.portfolio import Portfolio
from app.models.position import Position
from app.models.risk_config import RiskConfig
from app.pipeline.risk_manager.circuit_breaker import CircuitBreaker
from app.schemas.risk import RiskConfigResponse, RiskConfigUpdate, RiskStatusResponse

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/config", response_model=RiskConfigResponse)
async def get_risk_config(db: AsyncSession = Depends(get_db_session)):
    stmt = select(RiskConfig).where(RiskConfig.is_active == True)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="No active risk config found")
    return config


@router.put("/config", response_model=RiskConfigResponse)
async def update_risk_config(
    update: RiskConfigUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    stmt = select(RiskConfig).where(RiskConfig.is_active == True)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="No active risk config found")

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    await db.flush()
    return config


@router.get("/status", response_model=RiskStatusResponse)
async def get_risk_status(
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
):
    cb = CircuitBreaker()
    cb_status = await cb.get_status()

    # Get portfolio daily PnL
    stmt = select(Portfolio).limit(1)
    result = await db.execute(stmt)
    portfolio = result.scalar_one_or_none()

    # Count open positions
    pos_stmt = select(Position).where(Position.status == PositionStatus.OPEN.value)
    pos_result = await db.execute(pos_stmt)
    open_positions = len(pos_result.scalars().all())

    # Get risk config
    cfg_stmt = select(RiskConfig).where(RiskConfig.is_active == True)
    cfg_result = await db.execute(cfg_stmt)
    config = cfg_result.scalar_one_or_none()

    system_status = await redis.get("system:status") or "RUNNING"

    return RiskStatusResponse(
        circuit_breaker_active=cb_status["active"],
        system_status=system_status,
        daily_pnl=portfolio.daily_pnl if portfolio else 0,
        daily_loss_limit=config.max_daily_loss_pct if config else 0,
        open_positions=open_positions,
        max_positions=config.max_positions if config else 5,
    )
