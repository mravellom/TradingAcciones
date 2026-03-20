"""Paper vs Live execution comparison.

Compares fill quality, slippage, timing between paper and live modes.
"""
from decimal import Decimal

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ExecutionMode
from app.models.trade import Trade
from app.models.order import Order


class ComparisonService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_execution_comparison(self) -> dict:
        """Compare paper vs live execution metrics."""
        paper = await self._mode_stats(ExecutionMode.PAPER)
        live = await self._mode_stats(ExecutionMode.LIVE)

        return {
            "paper": paper,
            "live": live,
            "comparison": self._compute_diff(paper, live),
        }

    async def _mode_stats(self, mode: ExecutionMode) -> dict:
        """Get stats for a specific execution mode."""
        # Trade stats
        trade_stmt = select(
            func.count(Trade.id).label("total_trades"),
            func.sum(Trade.pnl).label("total_pnl"),
            func.avg(Trade.pnl).label("avg_pnl"),
            func.avg(Trade.pnl_percent).label("avg_return"),
            func.sum(case((Trade.pnl > 0, 1), else_=0)).label("wins"),
            func.avg(Trade.duration_seconds).label("avg_duration"),
        ).where(Trade.execution_mode == mode.value)

        result = await self._session.execute(trade_stmt)
        row = result.one()

        total = row.total_trades or 0
        wins = row.wins or 0

        # Slippage stats from orders
        slippage_stmt = select(
            func.avg(
                func.abs(Order.avg_fill_price - Order.requested_price)
            ).label("avg_slippage"),
            func.max(
                func.abs(Order.avg_fill_price - Order.requested_price)
            ).label("max_slippage"),
        ).where(
            Order.execution_mode == mode.value,
            Order.avg_fill_price.isnot(None),
            Order.status == "FILLED",
        )

        slip_result = await self._session.execute(slippage_stmt)
        slip_row = slip_result.one()

        return {
            "mode": mode.value,
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total, 4) if total > 0 else 0,
            "total_pnl": str(row.total_pnl or 0),
            "avg_pnl": str(round(row.avg_pnl or 0, 8)),
            "avg_return": str(round(row.avg_return or 0, 4)),
            "avg_duration_seconds": int(row.avg_duration or 0),
            "avg_slippage": str(round(slip_row.avg_slippage or 0, 8)),
            "max_slippage": str(round(slip_row.max_slippage or 0, 8)),
        }

    @staticmethod
    def _compute_diff(paper: dict, live: dict) -> dict:
        """Compute difference between paper and live metrics."""
        if paper["total_trades"] == 0 or live["total_trades"] == 0:
            return {"status": "insufficient_data", "message": "Need trades in both modes"}

        paper_wr = paper["win_rate"]
        live_wr = live["win_rate"]

        return {
            "status": "available",
            "win_rate_diff": round(live_wr - paper_wr, 4),
            "pnl_diff": str(
                Decimal(live["total_pnl"]) - Decimal(paper["total_pnl"])
            ),
            "slippage_diff": str(
                Decimal(live["avg_slippage"]) - Decimal(paper["avg_slippage"])
            ),
            "duration_diff_seconds": live["avg_duration_seconds"] - paper["avg_duration_seconds"],
        }
