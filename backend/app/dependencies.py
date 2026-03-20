from collections.abc import AsyncGenerator

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db():
        yield session


async def get_redis_client() -> Redis:
    return get_redis()


DbSession = Depends(get_db_session)
RedisClient = Depends(get_redis_client)
