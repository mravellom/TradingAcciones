"""Tests for PortfolioService atomic balance updates.

Validates:
- record_fill uses SQL UPDATE via session.execute
- record_close updates all fields atomically
- Insufficient balance raises ValueError
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.enums import ExecutionMode
from app.models.portfolio import Portfolio
from app.services.portfolio_service import PortfolioService


def _make_portfolio(**overrides):
    """Create a mock Portfolio with sensible defaults."""
    p = MagicMock(spec=Portfolio)
    p.id = overrides.get("id", uuid4())
    p.execution_mode = overrides.get("execution_mode", ExecutionMode.PAPER.value)
    p.total_balance = overrides.get("total_balance", Decimal("10000"))
    p.available_balance = overrides.get("available_balance", Decimal("8000"))
    p.allocated_balance = overrides.get("allocated_balance", Decimal("2000"))
    p.total_pnl = overrides.get("total_pnl", Decimal("0"))
    p.daily_pnl = overrides.get("daily_pnl", Decimal("0"))
    p.max_drawdown = overrides.get("max_drawdown", Decimal("0"))
    return p


@pytest.mark.asyncio
async def test_record_fill_uses_sql_update():
    """record_fill should use session.execute with an UPDATE statement, not ORM attribute sets."""
    session = AsyncMock()
    portfolio = _make_portfolio(available_balance=Decimal("5000"))

    # Mock _lock_portfolio to return our portfolio
    with patch.object(PortfolioService, "_lock_portfolio", return_value=portfolio):
        svc = PortfolioService(session)
        await svc.record_fill(ExecutionMode.PAPER, Decimal("1000"))

    # session.execute should have been called (for the UPDATE statement)
    assert session.execute.called, "record_fill must use session.execute for atomic SQL UPDATE"
    # session.flush should have been called to persist the update
    assert session.flush.called, "record_fill must flush after execute"


@pytest.mark.asyncio
async def test_record_close_updates_atomically():
    """record_close should update available, allocated, total_pnl, daily_pnl, total_balance."""
    session = AsyncMock()
    portfolio = _make_portfolio(
        available_balance=Decimal("7000"),
        allocated_balance=Decimal("3000"),
        total_pnl=Decimal("-100"),
        daily_pnl=Decimal("-100"),
        total_balance=Decimal("10000"),
    )

    with patch.object(PortfolioService, "_lock_portfolio", return_value=portfolio):
        svc = PortfolioService(session)
        await svc.record_close(
            mode=ExecutionMode.PAPER,
            position_value=Decimal("2000"),
            pnl=Decimal("150"),
        )

    # session.execute should have been called at least once for the atomic UPDATE
    assert session.execute.call_count >= 1, \
        "record_close must use session.execute for atomic SQL UPDATE"
    assert session.flush.called
    # session.refresh should be called to get updated values for drawdown check
    assert session.refresh.called


@pytest.mark.asyncio
async def test_insufficient_balance_raises_value_error():
    """record_fill should raise ValueError when available_balance < fill_value."""
    session = AsyncMock()
    portfolio = _make_portfolio(available_balance=Decimal("500"))

    with patch.object(PortfolioService, "_lock_portfolio", return_value=portfolio):
        svc = PortfolioService(session)
        with pytest.raises(ValueError, match="Insufficient balance"):
            await svc.record_fill(ExecutionMode.PAPER, Decimal("1000"))


@pytest.mark.asyncio
async def test_record_fill_portfolio_not_found_raises():
    """record_fill should raise ValueError when portfolio doesn't exist."""
    session = AsyncMock()

    with patch.object(PortfolioService, "_lock_portfolio", return_value=None):
        svc = PortfolioService(session)
        with pytest.raises(ValueError, match="Portfolio not found"):
            await svc.record_fill(ExecutionMode.PAPER, Decimal("100"))
