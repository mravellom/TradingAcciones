"""E2E test fixtures — real DB with isolated cleanup per test."""
import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


@pytest.fixture
async def db_engine():
    """Shared engine for E2E tests."""
    engine = create_async_engine(settings.database_url, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine):
    """Session factory that can create multiple sessions (like the app does)."""
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )
    yield factory

    # Cleanup all test data
    async with factory() as cleanup:
        for table in [
            "trades", "positions", "orders", "signals",
            "events", "portfolios",
        ]:
            await cleanup.execute(sqlalchemy.text(f"DELETE FROM {table}"))
        await cleanup.commit()


@pytest.fixture
async def session(session_factory):
    """Single session for tests that need direct DB access."""
    async with session_factory() as sess:
        yield sess
