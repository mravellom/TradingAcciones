"""Tests for circuit breaker persistence to DB event store.

Validates:
- activate persists CIRCUIT_BREAKER_ACTIVATED event to DB
- reset persists CIRCUIT_BREAKER_RESET event to DB
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.domain.enums import AggregateType, EventType
from app.pipeline.risk_manager.circuit_breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_activate_persists_to_db():
    """Activating circuit breaker with a session should write event to DB."""
    mock_redis = AsyncMock()

    mock_session = AsyncMock()
    mock_event_repo = AsyncMock()

    with patch("app.pipeline.risk_manager.circuit_breaker.get_redis", return_value=mock_redis):
        with patch(
            "app.repositories.event_repo.EventRepository",
            return_value=mock_event_repo,
        ):
            cb = CircuitBreaker()
            cb._redis = mock_redis
            await cb.activate("daily loss limit exceeded", session=mock_session)

    # Redis should be updated
    mock_redis.set.assert_any_call("circuit_breaker:active", "1")

    # DB event should be persisted
    mock_event_repo.append.assert_called_once()
    call_kwargs = mock_event_repo.append.call_args[1]
    assert call_kwargs["aggregate_type"] == AggregateType.SYSTEM
    assert call_kwargs["event_type"] == EventType.CIRCUIT_BREAKER_ACTIVATED
    assert call_kwargs["event_data"]["reason"] == "daily loss limit exceeded"

    # Session should be flushed
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_activate_without_session_skips_db():
    """Activating circuit breaker without session should only use Redis."""
    mock_redis = AsyncMock()

    with patch("app.pipeline.risk_manager.circuit_breaker.get_redis", return_value=mock_redis):
        cb = CircuitBreaker()
        cb._redis = mock_redis
        await cb.activate("test reason", session=None)

    # Redis should still be updated
    mock_redis.set.assert_any_call("circuit_breaker:active", "1")


@pytest.mark.asyncio
async def test_reset_persists_to_db():
    """Resetting circuit breaker with a session should write event to DB."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "daily loss limit"  # previous reason

    mock_session = AsyncMock()
    mock_event_repo = AsyncMock()

    with patch("app.pipeline.risk_manager.circuit_breaker.get_redis", return_value=mock_redis):
        with patch(
            "app.repositories.event_repo.EventRepository",
            return_value=mock_event_repo,
        ):
            cb = CircuitBreaker()
            cb._redis = mock_redis
            await cb.reset(session=mock_session)

    # Redis keys should be deleted
    mock_redis.delete.assert_called_once()

    # DB event should be persisted
    mock_event_repo.append.assert_called_once()
    call_kwargs = mock_event_repo.append.call_args[1]
    assert call_kwargs["aggregate_type"] == AggregateType.SYSTEM
    assert call_kwargs["event_type"] == EventType.CIRCUIT_BREAKER_RESET
    assert call_kwargs["event_data"]["previous_reason"] == "daily loss limit"

    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_reset_without_session_skips_db():
    """Resetting circuit breaker without session should only use Redis."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "some reason"

    with patch("app.pipeline.risk_manager.circuit_breaker.get_redis", return_value=mock_redis):
        cb = CircuitBreaker()
        cb._redis = mock_redis
        await cb.reset(session=None)

    mock_redis.delete.assert_called_once()
