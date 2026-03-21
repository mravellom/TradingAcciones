from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import PositionStatus
from app.models.position import Position
from app.repositories.base_repo import BaseRepository


class PositionRepository(BaseRepository[Position]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Position)

    async def get_open(self, limit: int = 100) -> list[Position]:
        stmt = (
            select(Position)
            .where(Position.status == PositionStatus.OPEN.value)
            .order_by(Position.opened_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_open_for_update(self, limit: int = 100) -> list[Position]:
        """Get open positions with row-level lock (SKIP LOCKED to avoid blocking)."""
        stmt = (
            select(Position)
            .where(Position.status == PositionStatus.OPEN.value)
            .with_for_update(skip_locked=True)
            .order_by(Position.opened_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_open_by_symbol(self, symbol: str) -> list[Position]:
        stmt = (
            select(Position)
            .where(
                Position.symbol == symbol,
                Position.status.in_([
                    PositionStatus.OPEN.value,
                    PositionStatus.PARTIALLY_CLOSED.value,
                ]),
            )
            .order_by(Position.opened_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_open(self) -> int:
        stmt = select(func.count()).where(
            Position.status == PositionStatus.OPEN.value
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_total_exposure_by_symbol(self, symbol: str) -> Decimal:
        """Get total allocated value for open positions on a symbol."""
        stmt = select(
            func.coalesce(
                func.sum(Position.entry_price * Position.quantity),
                Decimal("0"),
            )
        ).where(
            Position.symbol == symbol,
            Position.status.in_([
                PositionStatus.OPEN.value,
                PositionStatus.PARTIALLY_CLOSED.value,
            ]),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
