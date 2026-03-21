from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.dependencies import get_db_session, get_redis_client
from app.domain.enums import ExecutionMode, OrderStatus, PositionStatus
from app.models.order import Order
from app.models.position import Position

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
):
    checks = {}

    # Database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = {"status": "healthy"}
    except Exception as e:
        checks["database"] = {"status": "unhealthy", "error": str(e)}

    # Redis
    try:
        await redis.ping()
        checks["redis"] = {"status": "healthy"}
    except Exception as e:
        checks["redis"] = {"status": "unhealthy", "error": str(e)}

    # System status
    system_status = await redis.get("system:status") or "RUNNING"

    all_healthy = all(c["status"] == "healthy" for c in checks.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "system_status": system_status,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/halt")
async def halt_system(
    reason: str = "Manual halt",
    redis: Redis = Depends(get_redis_client),
    _auth: str = Depends(verify_api_key),
):
    """Kill switch: halt the entire trading system."""
    await redis.set("system:status", "HALTED")
    return {"status": "HALTED", "reason": reason}


@router.post("/resume")
async def resume_system(
    redis: Redis = Depends(get_redis_client),
    _auth: str = Depends(verify_api_key),
):
    """Resume the trading system after a halt."""
    # Check circuit breaker
    cb_active = await redis.get("circuit_breaker:active")
    if cb_active == "1":
        return {
            "status": "BLOCKED",
            "reason": "Circuit breaker is active. Reset it first via /risk/circuit-breaker/reset",
        }
    await redis.set("system:status", "RUNNING")
    return {"status": "RUNNING"}


@router.get("/reconciliation-status")
async def reconciliation_status(
    db: AsyncSession = Depends(get_db_session),
    _auth: str = Depends(verify_api_key),
):
    """Check for any state inconsistencies between DB and expected state.

    Returns stuck orders, positions without exchange IDs, etc.
    Useful for manual monitoring even if runtime_reconciler is running.
    """
    issues = []

    # Stuck SUBMITTING orders
    stmt = select(Order).where(Order.status == OrderStatus.SUBMITTING.value)
    result = await db.execute(stmt)
    stuck_orders = list(result.scalars().all())
    for o in stuck_orders:
        issues.append({
            "type": "STUCK_SUBMITTING",
            "order_id": str(o.id),
            "symbol": o.symbol,
            "created_at": o.created_at.isoformat() if o.created_at else "",
        })

    # LIVE positions without exchange_order_id on their entry order
    stmt = (
        select(Position)
        .where(
            and_(
                Position.status == PositionStatus.OPEN.value,
                Position.execution_mode == ExecutionMode.LIVE.value,
            )
        )
    )
    result = await db.execute(stmt)
    live_positions = list(result.scalars().all())
    for pos in live_positions:
        order = await db.get(Order, pos.entry_order_id)
        if order and not order.exchange_order_id:
            issues.append({
                "type": "POSITION_NO_EXCHANGE_ID",
                "position_id": str(pos.id),
                "order_id": str(order.id),
                "symbol": pos.symbol,
            })

    return {
        "status": "clean" if not issues else "issues_found",
        "issue_count": len(issues),
        "issues": issues,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
