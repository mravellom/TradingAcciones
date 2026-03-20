"""Shadow trade tracker — simulates what ML signals WOULD have done.

For each shadow signal, tracks:
- Would the TP have been hit?
- Would the SL have been hit?
- What would the PnL be?

Uses actual market data AFTER the signal to evaluate.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.signal import Signal

logger = get_logger(__name__)


async def evaluate_shadow_signals(
    session: AsyncSession,
    exchange_client,
    tp_pct: float = 0.015,
    sl_pct: float = 0.01,
    horizon_hours: int = 24,
) -> list[dict]:
    """Evaluate all shadow signals against what actually happened.

    Returns list of evaluated shadow trades.
    """
    # Get shadow signals
    stmt = (
        select(Signal)
        .where(Signal.indicators["source"].astext == "ml_shadow")
        .order_by(Signal.created_at.desc())
        .limit(200)
    )
    result = await session.execute(stmt)
    shadow_signals = list(result.scalars().all())

    if not shadow_signals:
        return []

    evaluations = []
    now = datetime.now(timezone.utc)

    for sig in shadow_signals:
        # Skip signals too recent to evaluate
        hours_since = (now - sig.created_at).total_seconds() / 3600
        if hours_since < horizon_hours:
            evaluations.append({
                "signal_id": str(sig.id),
                "symbol": sig.symbol,
                "created_at": sig.created_at.isoformat(),
                "status": "pending",
                "hours_elapsed": round(hours_since, 1),
            })
            continue

        # Fetch klines from signal time to signal time + horizon
        try:
            klines = await exchange_client.get_klines(
                sig.symbol, "1h", limit=horizon_hours + 5
            )
        except Exception:
            continue

        if not klines:
            continue

        entry_price = float(sig.entry_price)
        tp_price = entry_price * (1 + tp_pct)
        sl_price = entry_price * (1 - sl_pct)

        # Check what would have happened
        outcome = "timeout"
        bars_to_hit = horizon_hours
        exit_price = entry_price

        for i, k in enumerate(klines[:horizon_hours]):
            if float(k.high) >= tp_price:
                outcome = "tp_hit"
                bars_to_hit = i + 1
                exit_price = tp_price
                break
            if float(k.low) <= sl_price:
                outcome = "sl_hit"
                bars_to_hit = i + 1
                exit_price = sl_price
                break

        if outcome == "timeout":
            exit_price = float(klines[min(horizon_hours, len(klines) - 1)].close)

        pnl_pct = (exit_price - entry_price) / entry_price

        evaluations.append({
            "signal_id": str(sig.id),
            "symbol": sig.symbol,
            "created_at": sig.created_at.isoformat(),
            "status": "evaluated",
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "outcome": outcome,
            "pnl_pct": round(pnl_pct * 100, 3),
            "bars_to_hit": bars_to_hit,
            "confidence": str(sig.confidence),
            "ml_probability": sig.indicators.get("ml_probability", 0),
        })

    return evaluations


def summarize_shadow_performance(evaluations: list[dict]) -> dict:
    """Summarize shadow signal performance."""
    evaluated = [e for e in evaluations if e["status"] == "evaluated"]
    pending = [e for e in evaluations if e["status"] == "pending"]

    if not evaluated:
        return {
            "total_signals": len(evaluations),
            "evaluated": 0,
            "pending": len(pending),
            "status": "insufficient_data",
        }

    wins = [e for e in evaluated if e["outcome"] == "tp_hit"]
    losses = [e for e in evaluated if e["outcome"] == "sl_hit"]
    timeouts = [e for e in evaluated if e["outcome"] == "timeout"]

    total = len(evaluated)
    win_rate = len(wins) / total if total > 0 else 0
    avg_pnl = sum(e["pnl_pct"] for e in evaluated) / total if total > 0 else 0

    gross_profit = sum(e["pnl_pct"] for e in evaluated if e["pnl_pct"] > 0)
    gross_loss = abs(sum(e["pnl_pct"] for e in evaluated if e["pnl_pct"] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    return {
        "total_signals": len(evaluations),
        "evaluated": total,
        "pending": len(pending),
        "wins": len(wins),
        "losses": len(losses),
        "timeouts": len(timeouts),
        "win_rate": round(win_rate, 4),
        "avg_pnl_pct": round(avg_pnl, 4),
        "profit_factor": round(profit_factor, 2),
        "status": "ready" if total >= 20 else "collecting",
    }
