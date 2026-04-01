import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade import Trade
from app.repositories.base_repo import BaseRepository


class TradeRepository(BaseRepository[Trade]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Trade)

    async def get_by_symbol(self, symbol: str, limit: int = 100) -> list[Trade]:
        stmt = (
            select(Trade)
            .where(Trade.symbol == symbol)
            .order_by(Trade.closed_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_asset_class(self, asset_class: str, limit: int = 100) -> list[Trade]:
        stmt = (
            select(Trade)
            .where(Trade.asset_class == asset_class)
            .order_by(Trade.closed_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_strategy(
        self, strategy_id: uuid.UUID, limit: int = 100
    ) -> list[Trade]:
        stmt = (
            select(Trade)
            .where(Trade.strategy_id == strategy_id)
            .order_by(Trade.closed_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_date_range(
        self, start: datetime, end: datetime, limit: int = 500
    ) -> list[Trade]:
        stmt = (
            select(Trade)
            .where(Trade.closed_at >= start, Trade.closed_at <= end)
            .order_by(Trade.closed_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_win_rate(self, strategy_id: uuid.UUID | None = None) -> float:
        """Calculate win rate (trades with positive PnL / total trades)."""
        base = select(func.count()).select_from(Trade)
        wins = select(func.count()).select_from(Trade).where(Trade.pnl > 0)

        if strategy_id:
            base = base.where(Trade.strategy_id == strategy_id)
            wins = wins.where(Trade.strategy_id == strategy_id)

        total_result = await self.session.execute(base)
        total = total_result.scalar_one()

        if total == 0:
            return 0.0

        wins_result = await self.session.execute(wins)
        win_count = wins_result.scalar_one()

        return win_count / total
