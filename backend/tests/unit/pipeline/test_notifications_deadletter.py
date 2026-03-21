"""Tests for notification dead-letter queue.

Validates:
- Failed Telegram send writes to Redis dead letter queue
- Dead letter entries contain message, error, and timestamp
- Dead letter queue is trimmed to last 100 entries
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.notifications import TelegramNotifier


@pytest.mark.asyncio
async def test_failed_send_writes_to_dead_letter():
    """When Telegram send fails with an exception, message goes to Redis dead letter."""
    mock_redis = AsyncMock()

    notifier = TelegramNotifier(bot_token="fake-token", chat_id="12345")

    # Mock httpx to raise an exception
    with patch("app.core.notifications.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.side_effect = ConnectionError("Network unreachable")
        mock_client_cls.return_value = mock_client

        with patch("app.core.notifications.get_redis", return_value=mock_redis):
            result = await notifier.send("Test alert message")

    assert result is False

    # Verify dead letter was written to Redis
    mock_redis.lpush.assert_called_once()
    call_args = mock_redis.lpush.call_args
    assert call_args[0][0] == "notifications:dead_letter"

    # Parse the stored JSON
    stored_data = json.loads(call_args[0][1])
    assert "Test alert message" in stored_data["message"]
    assert "Network unreachable" in stored_data["error"]
    assert "timestamp" in stored_data

    # Verify trim to 100 entries
    mock_redis.ltrim.assert_called_once_with("notifications:dead_letter", 0, 99)


@pytest.mark.asyncio
async def test_http_error_status_writes_to_dead_letter():
    """When Telegram returns non-200 status, message goes to dead letter."""
    mock_redis = AsyncMock()

    notifier = TelegramNotifier(bot_token="fake-token", chat_id="12345")

    mock_response = MagicMock()
    mock_response.status_code = 429  # Rate limited
    mock_response.text = "Too Many Requests"

    with patch("app.core.notifications.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with patch("app.core.notifications.get_redis", return_value=mock_redis):
            result = await notifier.send("Rate limited message")

    assert result is False

    mock_redis.lpush.assert_called_once()
    stored_data = json.loads(mock_redis.lpush.call_args[0][1])
    assert "HTTP 429" in stored_data["error"]


@pytest.mark.asyncio
async def test_disabled_notifier_skips_send():
    """Notifier with no token/chat_id should return False without sending."""
    notifier = TelegramNotifier(bot_token="", chat_id="")

    assert notifier.enabled is False

    result = await notifier.send("Should not be sent")
    assert result is False


@pytest.mark.asyncio
async def test_successful_send_does_not_write_dead_letter():
    """Successful Telegram send should NOT write to dead letter."""
    mock_redis = AsyncMock()

    notifier = TelegramNotifier(bot_token="fake-token", chat_id="12345")

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("app.core.notifications.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with patch("app.core.notifications.get_redis", return_value=mock_redis):
            result = await notifier.send("Success message")

    assert result is True
    mock_redis.lpush.assert_not_called()
