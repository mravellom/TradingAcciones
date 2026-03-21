"""Tests for startup reconciliation.

Validates:
- Orphaned SUBMITTING orders get cancelled
- Redis SHUTTING_DOWN status is cleaned
- Circuit breaker recovery from DB event store
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.enums import (
    EventType,
    ExecutionMode,
    OrderSide,
    OrderStatus,
)
from app.tasks.startup_reconciler import (
    _clean_redis_status,
    _reconcile_orphaned_orders,
    _recover_circuit_breaker,
    reconcile,
)


def _make_orphaned_order(**overrides):
    """Create a mock Order stuck in SUBMITTING state."""
    order = MagicMock()
    order.id = overrides.get("id", uuid4())
    order.symbol = overrides.get("symbol", "BTCUSDT")
    order.side = overrides.get("side", OrderSide.BUY.value)
    order.status = overrides.get("status", OrderStatus.SUBMITTING.value)
    order.execution_mode = overrides.get("execution_mode", ExecutionMode.PAPER.value)
    order.requested_price = overrides.get("requested_price", Decimal("50000"))
    order.created_at = overrides.get(
        "created_at",
        datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    return order


@pytest.mark.asyncio
async def test_orphaned_submitting_orders_get_cancelled():
    """Orders stuck in SUBMITTING state should be marked as CANCELLED on startup."""
    order1 = _make_orphaned_order()
    order2 = _make_orphaned_order(symbol="ETHUSDT")

    session = AsyncMock()
    # Mock the query to return orphaned orders
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [order1, order2]
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    await _reconcile_orphaned_orders(session, executor=None)

    # Both orders should be marked as CANCELLED
    assert order1.status == OrderStatus.CANCELLED.value
    assert order2.status == OrderStatus.CANCELLED.value
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_redis_shutting_down_status_cleaned():
    """SHUTTING_DOWN status in Redis should be reset to RUNNING on startup."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "SHUTTING_DOWN"

    with patch("app.tasks.startup_reconciler.get_redis", return_value=mock_redis):
        await _clean_redis_status()

    mock_redis.set.assert_called_once_with("system:status", "RUNNING")


@pytest.mark.asyncio
async def test_redis_none_status_cleaned():
    """None status in Redis (fresh start) should be set to RUNNING."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch("app.tasks.startup_reconciler.get_redis", return_value=mock_redis):
        await _clean_redis_status()

    mock_redis.set.assert_called_once_with("system:status", "RUNNING")


@pytest.mark.asyncio
async def test_redis_running_status_not_overwritten():
    """RUNNING status in Redis should not be touched."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "RUNNING"

    with patch("app.tasks.startup_reconciler.get_redis", return_value=mock_redis):
        await _clean_redis_status()

    mock_redis.set.assert_not_called()


@pytest.mark.asyncio
async def test_circuit_breaker_recovered_from_db():
    """If DB shows CB activated without a reset, Redis should be re-activated."""
    mock_redis = AsyncMock()

    # Mock DB event: last CB event was ACTIVATED
    mock_event = MagicMock()
    mock_event.event_type = EventType.CIRCUIT_BREAKER_ACTIVATED.value
    mock_event.event_data = {"reason": "daily loss limit", "activated_at": "2026-03-20T10:00:00+00:00"}
    mock_event.created_at = datetime.now(timezone.utc) - timedelta(hours=1)

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_event
    session.execute.return_value = mock_result

    with patch("app.tasks.startup_reconciler.get_redis", return_value=mock_redis):
        await _recover_circuit_breaker(session)

    # Redis should have CB re-activated
    mock_redis.set.assert_any_call("circuit_breaker:active", "1")
    mock_redis.set.assert_any_call("circuit_breaker:reason", "daily loss limit")


@pytest.mark.asyncio
async def test_circuit_breaker_cleaned_when_db_shows_reset():
    """If DB shows CB was reset but Redis says active, trust DB and clean Redis."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "1"  # Redis says active

    # Mock DB event: last CB event was RESET
    mock_event = MagicMock()
    mock_event.event_type = EventType.CIRCUIT_BREAKER_RESET.value

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_event
    session.execute.return_value = mock_result

    with patch("app.tasks.startup_reconciler.get_redis", return_value=mock_redis):
        await _recover_circuit_breaker(session)

    # Redis CB keys should be deleted
    mock_redis.delete.assert_called()
