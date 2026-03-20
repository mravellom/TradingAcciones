"""Integration test fixtures — uses real PostgreSQL."""
import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


@pytest.fixture
async def session():
    """Session with cleanup after each test."""
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as sess:
        yield sess

    # Cleanup test data
    async with factory() as cleanup:
        for table in ["trades", "positions", "orders", "signals", "events", "portfolios"]:
            await cleanup.execute(sqlalchemy.text(f"DELETE FROM {table}"))
        await cleanup.commit()

    await engine.dispose()
