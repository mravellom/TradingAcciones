from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.dependencies import get_db_session, get_redis_client

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
