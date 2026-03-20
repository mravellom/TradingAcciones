from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ExecutionMode
from app.models.portfolio import Portfolio
from app.repositories.base_repo import BaseRepository


class PortfolioRepository(BaseRepository[Portfolio]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Portfolio)

    async def get_by_mode(self, mode: ExecutionMode) -> Portfolio | None:
        stmt = select(Portfolio).where(Portfolio.execution_mode == mode.value)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
