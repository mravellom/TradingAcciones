import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import OrderStatus
from app.domain.state_machine import ORDER_TERMINAL_STATES
from app.models.order import Order
from app.repositories.base_repo import BaseRepository


class OrderRepository(BaseRepository[Order]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Order)

    async def get_by_signal(self, signal_id: uuid.UUID) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.signal_id == signal_id)
            .order_by(Order.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_status(self, status: OrderStatus, limit: int = 100) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.status == status.value)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active(self, limit: int = 100) -> list[Order]:
        """Get non-terminal orders."""
        terminal = [s.value for s in ORDER_TERMINAL_STATES]
        stmt = (
            select(Order)
            .where(Order.status.notin_(terminal))
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_symbol(self, symbol: str, limit: int = 100) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.symbol == symbol)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_asset_class(self, asset_class: str, limit: int = 100) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.asset_class == asset_class)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
