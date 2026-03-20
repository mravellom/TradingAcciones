import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model: type[T]):
        self.session = session
        self.model = model

    async def get_by_id(self, id: uuid.UUID) -> T | None:
        return await self.session.get(self.model, id)

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()
