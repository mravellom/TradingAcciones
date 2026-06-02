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

    # ── Advanced metrics ──

    async def _get_trades(
        self,
        profile: str | None = None,
        asset_class: str | None = None,
        symbol: str | None = None,
    ) -> list[Trade]:
        """Fetch trades with optional filters."""
        stmt = select(Trade).order_by(Trade.closed_at)
        if profile:
            stmt = stmt.where(Trade.risk_profile_type == profile)
        if asset_class:
            stmt = stmt.where(Trade.asset_class == asset_class)
        if symbol:
            stmt = stmt.where(Trade.symbol == symbol)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _compute_advanced_metrics(trades: list[Trade]) -> dict:
        """Compute advanced financial metrics from a list of trades."""
        if not trades:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0,
                "total_pnl": "0",
                "avg_pnl": "0",
                "profit_factor": 0,
                "expectancy": 0,
                "avg_win": "0",
                "avg_loss": "0",
                "best_trade": "0",
                "worst_trade": "0",
                "max_drawdown": "0",
                "max_drawdown_pct": 0,
                "avg_duration_seconds": 0,
                "trades_per_day": 0,
                "avg_hold_hours": 0,
            }

        pnls = [float(t.pnl) for t in trades]
        pnl_pcts = [float(t.pnl_percent) for t in trades]

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total = len(pnls)
        n_wins = len(wins)
        n_losses = len(losses)
        win_rate = n_wins / total if total > 0 else 0

        total_pnl = sum(pnls)
        avg_pnl = total_pnl / total if total > 0 else 0

        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        profit_factor = min(profit_factor, 999)

        avg_win = sum(wins) / n_wins if n_wins > 0 else 0
        avg_loss = abs(sum(losses)) / n_losses if n_losses > 0 else 0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # Max drawdown from cumulative PnL
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnls:
            cumulative += p
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        max_dd_pct = max_dd / peak if peak > 0 else 0

        # Frequency
        durations = [t.duration_seconds for t in trades]
        avg_duration = sum(durations) / total if total > 0 else 0

        first_trade = trades[0].closed_at
        last_trade = trades[-1].closed_at
        days_span = max((last_trade - first_trade).days, 1)
        trades_per_day = round(total / days_span, 2)

        avg_hold_hours = round(avg_duration / 3600, 1)

        return {
            "total_trades": total,
            "wins": n_wins,
            "losses": n_losses,
            "win_rate": round(win_rate, 4),
            "total_pnl": str(round(total_pnl, 8)),
            "avg_pnl": str(round(avg_pnl, 8)),
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(expectancy, 6),
            "avg_win": str(round(avg_win, 8)),
            "avg_loss": str(round(avg_loss, 8)),
            "best_trade": str(round(max(pnls), 8)),
            "worst_trade": str(round(min(pnls), 8)),
            "max_drawdown": str(round(max_dd, 8)),
            "max_drawdown_pct": round(max_dd_pct, 4),
            "avg_duration_seconds": int(avg_duration),
            "trades_per_day": trades_per_day,
            "avg_hold_hours": avg_hold_hours,
        }

    async def get_per_profile_performance(self, asset_class: str | None = None) -> list[dict]:
        """Get performance breakdown by risk profile type."""
        profiles = ["ULTRA_CONSERVADOR", "DEFENSIVO_AGRESIVO"]
        results = []
        for profile in profiles:
            trades = await self._get_trades(profile=profile, asset_class=asset_class)
            metrics = self._compute_advanced_metrics(trades)
            metrics["profile_type"] = profile
            results.append(metrics)
        return results

    async def get_per_symbol_performance(self, asset_class: str | None = None) -> list[dict]:
        """Get performance breakdown by symbol."""
        # Get distinct symbols
        stmt = select(Trade.symbol).distinct()
        if asset_class:
            stmt = stmt.where(Trade.asset_class == asset_class)
        result = await self._session.execute(stmt)
        symbols = [row[0] for row in result.all()]

        results = []
        for symbol in sorted(symbols):
            trades = await self._get_trades(symbol=symbol, asset_class=asset_class)
            metrics = self._compute_advanced_metrics(trades)
            metrics["symbol"] = symbol
            results.append(metrics)
        return results

    async def get_advanced_summary(self, asset_class: str | None = None) -> dict:
        """Get summary with advanced financial metrics (profit factor, expectancy, etc.)."""
        trades = await self._get_trades(asset_class=asset_class)
        metrics = self._compute_advanced_metrics(trades)

        open_stmt = select(func.count()).where(
            Position.status == PositionStatus.OPEN.value
        )
        open_result = await self._session.execute(open_stmt)
        metrics["open_positions"] = open_result.scalar_one()

        return metrics

    async def get_profile_comparison(self) -> dict:
        """Direct side-by-side comparison of both risk profiles."""
        ultra = await self._get_trades(profile="ULTRA_CONSERVADOR")
        defensivo = await self._get_trades(profile="DEFENSIVO_AGRESIVO")

        ultra_metrics = self._compute_advanced_metrics(ultra)
        defensivo_metrics = self._compute_advanced_metrics(defensivo)

        # Determine which is better on each metric
        comparison = {}
        better_keys = {
            "win_rate": "higher",
            "profit_factor": "higher",
            "expectancy": "higher",
            "max_drawdown_pct": "lower",
            "trades_per_day": "info",
        }
        for key, direction in better_keys.items():
            u_val = ultra_metrics.get(key, 0)
            d_val = defensivo_metrics.get(key, 0)
            if direction == "higher":
                comparison[key] = "ULTRA_CONSERVADOR" if u_val >= d_val else "DEFENSIVO_AGRESIVO"
            elif direction == "lower":
                comparison[key] = "ULTRA_CONSERVADOR" if u_val <= d_val else "DEFENSIVO_AGRESIVO"
            else:
                comparison[key] = "info"

        return {
            "ULTRA_CONSERVADOR": ultra_metrics,
            "DEFENSIVO_AGRESIVO": defensivo_metrics,
            "better_on": comparison,
            "note": "Requires trades under both profiles for meaningful comparison",
        }
