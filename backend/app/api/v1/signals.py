import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session
from app.repositories.signal_repo import SignalRepository
from app.schemas.signal import SignalResponse

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/", response_model=list[SignalResponse])
async def list_signals(
    symbol: str | None = Query(None),
    asset_class: str | None = Query(None, pattern="^(CRYPTO|STOCKS)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    repo = SignalRepository(db)
    if asset_class:
        signals = await repo.get_by_asset_class(asset_class, limit=limit)
    elif symbol:
        signals = await repo.get_by_symbol(symbol.upper(), limit=limit)
    else:
        signals = await repo.get_all(limit=limit)
    return signals


@router.get("/active", response_model=list[SignalResponse])
async def list_active_signals(
    db: AsyncSession = Depends(get_db_session),
):
    repo = SignalRepository(db)
    signals = await repo.get_active()
    return signals


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(
    signal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    repo = SignalRepository(db)
    signal = await repo.get_by_id(signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal
