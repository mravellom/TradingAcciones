from unittest.mock import AsyncMock, patch

import pytest

from app.core.notifications import TelegramNotifier


class TestTelegramNotifier:
    def test_disabled_without_config(self):
        n = TelegramNotifier(bot_token="", chat_id="")
        assert not n.enabled

    def test_enabled_with_config(self):
        n = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        assert n.enabled

    @pytest.mark.asyncio
    async def test_send_disabled_returns_false(self):
        n = TelegramNotifier(bot_token="", chat_id="")
        result = await n.send("test message")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        n = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("app.core.notifications.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await n.send("test")
            assert result is True
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure_returns_false(self):
        n = TelegramNotifier(bot_token="123:ABC", chat_id="456")

        with patch("app.core.notifications.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await n.send("test")
            assert result is False
