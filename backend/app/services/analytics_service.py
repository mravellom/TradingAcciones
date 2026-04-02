from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade import Trade
from app.models.position import Position
from app.models.portfolio import Portfolio
from app.domain.enums import PositionStatus


class AnalyticsService:
    """Calculates trading performance metrics."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_cumulative_pnl(self, days: int = 30, asset_class: str | None = None) -> list[dict]:
        """Get daily cumulative PnL for the last N days."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(
                func.date(Trade.closed_at).label("date"),
                func.sum(Trade.pnl).label("daily_pnl"),
            )
            .where(Trade.closed_at >= since)
            .group_by(func.date(Trade.closed_at))
            .order_by(func.date(Trade.closed_at))
        )
        if asset_class:
            stmt = stmt.where(Trade.asset_class == asset_class)
        result = await self._session.execute(stmt)
        rows = result.all()

        cumulative = Decimal("0")
        data = []
        for row in rows:
            cumulative += row.daily_pnl
            data.append({
                "date": str(row.date),
                "daily_pnl": str(row.daily_pnl),
                "cumulative_pnl": str(cumulative),
            })
        return data

    async def get_per_strategy_performance(self, asset_class: str | None = None) -> list[dict]:
        """Get performance breakdown per strategy."""
        stmt = select(
            Trade.strategy_id,
            func.count(Trade.id).label("total_trades"),
            func.sum(Trade.pnl).label("total_pnl"),
            func.avg(Trade.pnl).label("avg_pnl"),
            func.sum(case((Trade.pnl > 0, 1), else_=0)).label("wins"),
            func.sum(case((Trade.pnl <= 0, 1), else_=0)).label("losses"),
            func.avg(Trade.pnl_percent).label("avg_pnl_percent"),
            func.max(Trade.pnl).label("best_trade"),
            func.min(Trade.pnl).label("worst_trade"),
            func.avg(Trade.duration_seconds).label("avg_duration"),
        )
        if asset_class:
            stmt = stmt.where(Trade.asset_class == asset_class)
        stmt = stmt.group_by(Trade.strategy_id)

        result = await self._session.execute(stmt)
        rows = result.all()

        data = []
        for row in rows:
            total = row.total_trades or 0
            wins = row.wins or 0
            win_rate = wins / total if total > 0 else 0

            data.append({
                "strategy_id": str(row.strategy_id),
                "total_trades": total,
                "wins": wins,
                "losses": row.losses or 0,
                "win_rate": round(win_rate, 4),
                "total_pnl": str(row.total_pnl or 0),
                "avg_pnl": str(round(row.avg_pnl or 0, 8)),
                "avg_pnl_percent": str(round(row.avg_pnl_percent or 0, 4)),
                "best_trade": str(row.best_trade or 0),
                "worst_trade": str(row.worst_trade or 0),
                "avg_duration_seconds": int(row.avg_duration or 0),
            })
        return data

    async def get_drawdown_series(self, days: int = 30, asset_class: str | None = None) -> list[dict]:
        """Get drawdown over time."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(
                func.date(Trade.closed_at).label("date"),
                func.sum(Trade.pnl).label("daily_pnl"),
            )
            .where(Trade.closed_at >= since)
            .group_by(func.date(Trade.closed_at))
            .order_by(func.date(Trade.closed_at))
        )
        if asset_class:
            stmt = stmt.where(Trade.asset_class == asset_class)
        result = await self._session.execute(stmt)
        rows = result.all()

        cumulative = Decimal("0")
        peak = Decimal("0")
        data = []
        for row in rows:
            cumulative += row.daily_pnl
            if cumulative > peak:
                peak = cumulative
            drawdown = (peak - cumulative) if peak > 0 else Decimal("0")
            dd_pct = drawdown / peak if peak > 0 else Decimal("0")
            data.append({
                "date": str(row.date),
                "cumulative_pnl": str(cumulative),
                "peak": str(peak),
                "drawdown": str(drawdown),
                "drawdown_pct": str(round(dd_pct, 4)),
            })
        return data

    async def get_summary(self, asset_class: str | None = None) -> dict:
        """Get overall trading summary."""
        stmt = select(
            func.count(Trade.id).label("total_trades"),
            func.sum(Trade.pnl).label("total_pnl"),
            func.avg(Trade.pnl).label("avg_pnl"),
            func.sum(case((Trade.pnl > 0, 1), else_=0)).label("wins"),
            func.avg(Trade.duration_seconds).label("avg_duration"),
            func.avg(Trade.pnl_percent).label("avg_return"),
        )
        if asset_class:
            stmt = stmt.where(Trade.asset_class == asset_class)
        result = await self._session.execute(stmt)
        row = result.one()

        total = row.total_trades or 0
        wins = row.wins or 0

        open_stmt = select(func.count()).where(
            Position.status == PositionStatus.OPEN.value
        )
        open_result = await self._session.execute(open_stmt)
        open_count = open_result.scalar_one()

        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total, 4) if total > 0 else 0,
            "total_pnl": str(row.total_pnl or 0),
            "avg_pnl": str(round(row.avg_pnl or 0, 8)),
            "avg_return": str(round(row.avg_return or 0, 4)),
            "avg_duration_seconds": int(row.avg_duration or 0),
            "open_positions": open_count,
        }
