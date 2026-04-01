import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.signal import Signal
from app.repositories.base_repo import BaseRepository


class SignalRepository(BaseRepository[Signal]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Signal)

    async def get_by_symbol(
        self, symbol: str, limit: int = 50
    ) -> list[Signal]:
        stmt = (
            select(Signal)
            .where(Signal.symbol == symbol)
            .order_by(Signal.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_asset_class(
        self, asset_class: str, limit: int = 50
    ) -> list[Signal]:
        stmt = (
            select(Signal)
            .where(Signal.asset_class == asset_class)
            .order_by(Signal.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_strategy(
        self, strategy_id: uuid.UUID, limit: int = 50
    ) -> list[Signal]:
        stmt = (
            select(Signal)
            .where(Signal.strategy_id == strategy_id)
            .order_by(Signal.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active(self, now: datetime | None = None) -> list[Signal]:
        """Get signals that haven't expired yet."""
        if now is None:
            from datetime import timezone
            now = datetime.now(timezone.utc)
        stmt = (
            select(Signal)
            .where(Signal.expires_at > now)
            .order_by(Signal.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
