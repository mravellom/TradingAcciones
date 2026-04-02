from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session
from app.services.analytics_service import AnalyticsService
from app.services.comparison_service import ComparisonService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
async def get_summary(
    asset_class: str | None = Query(None, pattern="^(CRYPTO|STOCKS)$"),
    db: AsyncSession = Depends(get_db_session),
):
    """Get trading performance summary. Filter by asset_class (CRYPTO|STOCKS)."""
    svc = AnalyticsService(db)
    return await svc.get_summary(asset_class)


@router.get("/pnl")
async def get_cumulative_pnl(
    days: int = Query(default=30, ge=1, le=365),
    asset_class: str | None = Query(None, pattern="^(CRYPTO|STOCKS)$"),
    db: AsyncSession = Depends(get_db_session),
):
    """Get daily cumulative PnL. Filter by asset_class (CRYPTO|STOCKS)."""
    svc = AnalyticsService(db)
    return await svc.get_cumulative_pnl(days, asset_class)


@router.get("/drawdown")
async def get_drawdown(
    days: int = Query(default=30, ge=1, le=365),
    asset_class: str | None = Query(None, pattern="^(CRYPTO|STOCKS)$"),
    db: AsyncSession = Depends(get_db_session),
):
    """Get drawdown series. Filter by asset_class (CRYPTO|STOCKS)."""
    svc = AnalyticsService(db)
    return await svc.get_drawdown_series(days, asset_class)


@router.get("/per-strategy")
async def get_per_strategy(
    asset_class: str | None = Query(None, pattern="^(CRYPTO|STOCKS)$"),
    db: AsyncSession = Depends(get_db_session),
):
    """Get performance per strategy. Filter by asset_class (CRYPTO|STOCKS)."""
    svc = AnalyticsService(db)
    return await svc.get_per_strategy_performance(asset_class)


@router.get("/paper-vs-live")
async def get_paper_vs_live(db: AsyncSession = Depends(get_db_session)):
    """Compare paper trading vs live trading performance metrics."""
    svc = ComparisonService(db)
    return await svc.get_execution_comparison()


@router.get("/ml-shadow")
async def get_ml_shadow_performance(db: AsyncSession = Depends(get_db_session)):
    """Get ML shadow signal performance — what ML WOULD have done."""
    from app.ml.serving.shadow_tracker import evaluate_shadow_signals, summarize_shadow_performance
    # Use a lightweight evaluator that doesn't need exchange (uses stored data)
    from sqlalchemy import select
    from app.models.signal import Signal

    stmt = (
        select(Signal)
        .where(Signal.indicators["source"].astext == "ml_shadow")
        .order_by(Signal.created_at.desc())
        .limit(200)
    )
    result = await db.execute(stmt)
    signals = list(result.scalars().all())

    if not signals:
        return {"status": "no_shadow_signals", "message": "Start the ML shadow scanner first"}

    # Basic stats from signal data
    total = len(signals)
    by_symbol = {}
    for sig in signals:
        sym = sig.symbol
        if sym not in by_symbol:
            by_symbol[sym] = {"count": 0, "avg_confidence": 0, "signals": []}
        by_symbol[sym]["count"] += 1
        by_symbol[sym]["avg_confidence"] += float(sig.confidence)
        by_symbol[sym]["signals"].append({
            "id": str(sig.id),
            "confidence": str(sig.confidence),
            "ml_probability": sig.indicators.get("ml_probability", 0),
            "entry_price": str(sig.entry_price),
            "created_at": sig.created_at.isoformat(),
        })

    for sym in by_symbol:
        by_symbol[sym]["avg_confidence"] = round(
            by_symbol[sym]["avg_confidence"] / by_symbol[sym]["count"], 4
        )
        by_symbol[sym]["signals"] = by_symbol[sym]["signals"][:10]  # Last 10 only

    return {
        "total_shadow_signals": total,
        "by_symbol": by_symbol,
        "note": "Run shadow scanner for 2+ weeks, then use evaluate_shadow_signals() with exchange data for full PnL evaluation",
    }
