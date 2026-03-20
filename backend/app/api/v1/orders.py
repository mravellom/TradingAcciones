import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.dependencies import get_db_session
from app.domain.enums import OrderStatus
from app.repositories.order_repo import OrderRepository
from app.schemas.order import OrderResponse
from app.services.approval_service import ApprovalService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/", response_model=list[OrderResponse])
async def list_orders(
    symbol: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    repo = OrderRepository(db)
    if status:
        orders = await repo.get_by_status(OrderStatus(status), limit=limit)
    elif symbol:
        orders = await repo.get_by_symbol(symbol.upper(), limit=limit)
    else:
        orders = await repo.get_all(limit=limit)
    return orders


@router.get("/active", response_model=list[OrderResponse])
async def list_active_orders(db: AsyncSession = Depends(get_db_session)):
    repo = OrderRepository(db)
    return await repo.get_active()


@router.get("/pending-approval", response_model=list[OrderResponse])
async def list_pending_approvals(db: AsyncSession = Depends(get_db_session)):
    svc = ApprovalService(db)
    return await svc.get_pending_approvals()


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)):
    repo = OrderRepository(db)
    order = await repo.get_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/{order_id}/approve", response_model=OrderResponse)
async def approve_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    _auth: str = Depends(verify_api_key),
):
    """Human approves a pending order for execution."""
    svc = ApprovalService(db)
    try:
        return await svc.approve(order_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{order_id}/reject")
async def reject_order(
    order_id: uuid.UUID,
    reason: str = "Manually rejected",
    db: AsyncSession = Depends(get_db_session),
    _auth: str = Depends(verify_api_key),
):
    """Human rejects a pending order."""
    svc = ApprovalService(db)
    try:
        return await svc.reject(order_id, reason)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
