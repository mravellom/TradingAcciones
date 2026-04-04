from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import verify_api_key
from app.dependencies import get_db_session, get_redis_client
from app.domain.enums import (
    AggregateType,
    EventType,
    PositionStatus,
    RiskProfileType,
)
from app.models.portfolio import Portfolio
from app.models.position import Position
from app.models.risk_config import RiskConfig
from app.pipeline.risk_manager.circuit_breaker import CircuitBreaker
from app.repositories.event_repo import EventRepository
from app.schemas.risk import (
    RiskConfigResponse,
    RiskConfigUpdate,
    RiskProfileHistoryEntry,
    RiskProfileResponse,
    RiskProfileSwitch,
    RiskStatusResponse,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/risk", tags=["risk"])

# Profile presets: values applied when switching profiles.
# max_daily_loss_pct and max_drawdown_pct are global — never changed by switch.
PROFILE_PRESETS: dict[RiskProfileType, dict] = {
    RiskProfileType.ULTRA_CONSERVADOR: {
        "min_confidence": Decimal("0.60"),
        "max_positions": 5,
        "max_exposure_per_symbol_pct": Decimal("0.10"),
        "risk_per_trade_pct": Decimal("0.01"),
        "allow_partial_signal_agreement": False,
        "min_agreeing_signals": 3,
        "use_atr_for_sl_tp": False,
        "atr_period": 14,
        "atr_sl_multiplier": Decimal("1.5"),
        "atr_tp_multiplier": Decimal("3.0"),
    },
    RiskProfileType.DEFENSIVO_AGRESIVO: {
        "min_confidence": Decimal("0.55"),
        "max_positions": 7,
        "max_exposure_per_symbol_pct": Decimal("0.15"),
        "risk_per_trade_pct": Decimal("0.015"),
        "allow_partial_signal_agreement": True,
        "min_agreeing_signals": 2,
        "use_atr_for_sl_tp": True,
        "atr_period": 14,
        "atr_sl_multiplier": Decimal("1.5"),
        "atr_tp_multiplier": Decimal("3.0"),
    },
}

REDIS_PROFILE_KEY = "risk:active_profile"


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
    _auth: str = Depends(verify_api_key),
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
        active_profile=config.profile_type if config else "ULTRA_CONSERVADOR",
    )


# ── Profile endpoints ──


@router.get("/profile", response_model=RiskProfileResponse)
async def get_risk_profile(db: AsyncSession = Depends(get_db_session)):
    """Get the active risk profile and its parameters."""
    stmt = select(RiskConfig).where(RiskConfig.is_active == True)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="No active risk config found")
    return config


@router.post("/profile/switch", response_model=RiskProfileResponse)
async def switch_risk_profile(
    body: RiskProfileSwitch,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
    _auth: str = Depends(verify_api_key),
):
    """Switch between risk profiles (ULTRA_CONSERVADOR / DEFENSIVO_AGRESIVO).

    Validates system is RUNNING, circuit breaker is off, and drawdown < 5%
    before allowing switch to DEFENSIVO_AGRESIVO.
    Open positions are NOT affected.
    """
    # 1. System must be RUNNING
    system_status = await redis.get("system:status") or "RUNNING"
    if system_status != "RUNNING":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot switch profile: system is {system_status}",
        )

    # 2. Circuit breaker must be off
    cb = CircuitBreaker()
    if await cb.is_active():
        raise HTTPException(
            status_code=409,
            detail="Cannot switch profile: circuit breaker is active",
        )

    # 3. Get active config
    stmt = select(RiskConfig).where(RiskConfig.is_active == True)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="No active risk config found")

    previous_profile = config.profile_type
    new_profile = body.profile_type

    # 4. No-op if already on requested profile
    if previous_profile == new_profile.value:
        return config

    # 5. Block switch to DEFENSIVO_AGRESIVO if drawdown > 5%
    if new_profile == RiskProfileType.DEFENSIVO_AGRESIVO:
        portfolio_stmt = select(Portfolio).limit(1)
        portfolio_result = await db.execute(portfolio_stmt)
        portfolio = portfolio_result.scalar_one_or_none()
        if portfolio and portfolio.max_drawdown >= Decimal("0.05"):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot switch to DEFENSIVO_AGRESIVO: current drawdown "
                f"({portfolio.max_drawdown:.2%}) exceeds 5% safety threshold",
            )

    # 6. Apply preset values
    preset = PROFILE_PRESETS[new_profile]
    config.profile_type = new_profile.value
    for field_name, value in preset.items():
        setattr(config, field_name, value)

    # 7. Record event
    event_repo = EventRepository(db)
    await event_repo.append(
        aggregate_type=AggregateType.SYSTEM,
        aggregate_id=uuid4(),
        event_type=EventType.RISK_PROFILE_CHANGED,
        event_data={
            "previous_profile": previous_profile,
            "new_profile": new_profile.value,
        },
    )

    await db.commit()

    # 8. Update Redis cache
    await redis.set(REDIS_PROFILE_KEY, new_profile.value)

    # 9. Publish to WebSocket via Redis pub/sub
    import json
    await redis.publish(
        "ws:risk",
        json.dumps({
            "event": "risk_profile_changed",
            "data": {
                "previous_profile": previous_profile,
                "new_profile": new_profile.value,
            },
        }),
    )

    logger.info(
        "risk_profile_switched",
        previous=previous_profile,
        new=new_profile.value,
    )

    return config


@router.get("/profile/history", response_model=list[RiskProfileHistoryEntry])
async def get_profile_history(
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session),
):
    """Get history of risk profile changes."""
    event_repo = EventRepository(db)
    events = await event_repo.get_by_type(
        EventType.RISK_PROFILE_CHANGED,
        limit=limit,
    )
    return [
        RiskProfileHistoryEntry(
            previous_profile=e.event_data.get("previous_profile", ""),
            new_profile=e.event_data.get("new_profile", ""),
            timestamp=e.created_at,
            event_data=e.event_data,
        )
        for e in events
    ]
