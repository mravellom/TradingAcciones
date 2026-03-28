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

    @pytest.mark.asyncio
    async def test_send_non_200_returns_false_and_dead_letters(self):
        n = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        mock_response = AsyncMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("app.core.notifications.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            with patch.object(n, "_dead_letter", new_callable=AsyncMock) as mock_dl:
                result = await n.send("test")
                assert result is False
                mock_dl.assert_called_once()


class TestNotifyConvenienceMethods:
    """Test all convenience notification methods."""

    def _make_notifier(self):
        n = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        n.send = AsyncMock(return_value=True)
        return n

    @pytest.mark.asyncio
    async def test_notify_fill(self):
        n = self._make_notifier()
        await n.notify_fill("BTCUSDT", "BUY", "0.5", "50000", "100.00")
        n.send.assert_called_once()
        msg = n.send.call_args[0][0]
        assert "ORDER FILLED" in msg
        assert "BTCUSDT" in msg
        assert "BUY" in msg
        assert "0.5" in msg
        assert "50000" in msg
        assert "100.00" in msg

    @pytest.mark.asyncio
    async def test_notify_fill_without_pnl(self):
        n = self._make_notifier()
        await n.notify_fill("ETHUSDT", "SELL", "1.0", "3000")
        msg = n.send.call_args[0][0]
        assert "ORDER FILLED" in msg
        assert "P&L" not in msg

    @pytest.mark.asyncio
    async def test_notify_stop_loss(self):
        n = self._make_notifier()
        await n.notify_stop_loss("BTCUSDT", "50000", "49000", "-100.00")
        msg = n.send.call_args[0][0]
        assert "STOP LOSS" in msg
        assert "BTCUSDT" in msg
        assert "49000" in msg

    @pytest.mark.asyncio
    async def test_notify_take_profit(self):
        n = self._make_notifier()
        await n.notify_take_profit("BTCUSDT", "50000", "55000", "500.00")
        msg = n.send.call_args[0][0]
        assert "TAKE PROFIT" in msg
        assert "55000" in msg

    @pytest.mark.asyncio
    async def test_notify_circuit_breaker(self):
        n = self._make_notifier()
        await n.notify_circuit_breaker("Daily loss exceeded 3%")
        msg = n.send.call_args[0][0]
        assert "CIRCUIT BREAKER" in msg
        assert "Daily loss exceeded 3%" in msg

    @pytest.mark.asyncio
    async def test_notify_system_halt(self):
        n = self._make_notifier()
        await n.notify_system_halt("Manual halt by operator")
        msg = n.send.call_args[0][0]
        assert "SYSTEM HALTED" in msg
        assert "Manual halt" in msg

    @pytest.mark.asyncio
    async def test_notify_system_resume(self):
        n = self._make_notifier()
        await n.notify_system_resume()
        msg = n.send.call_args[0][0]
        assert "SYSTEM RESUMED" in msg

    @pytest.mark.asyncio
    async def test_notify_pending_approval(self):
        n = self._make_notifier()
        await n.notify_pending_approval("order-123", "BTCUSDT", "BUY", "0.1", "50000")
        msg = n.send.call_args[0][0]
        assert "APPROVAL REQUIRED" in msg
        assert "order-123" in msg
        assert "BTCUSDT" in msg

    @pytest.mark.asyncio
    async def test_notify_daily_summary(self):
        n = self._make_notifier()
        await n.notify_daily_summary(10, "+250.00", "70%", "10250.00")
        msg = n.send.call_args[0][0]
        assert "DAILY SUMMARY" in msg
        assert "10" in msg
        assert "+250.00" in msg
        assert "70%" in msg


class TestDeadLetterQueue:
    @pytest.mark.asyncio
    async def test_dead_letter_stores_in_redis(self):
        n = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        mock_redis = AsyncMock()

        with patch("app.core.redis.get_redis", return_value=mock_redis):
            await n._dead_letter("failed message", "HTTP 500")

        mock_redis.lpush.assert_called_once()
        mock_redis.ltrim.assert_called_once_with("notifications:dead_letter", 0, 99)

    @pytest.mark.asyncio
    async def test_dead_letter_survives_redis_failure(self):
        n = TelegramNotifier(bot_token="123:ABC", chat_id="456")

        with patch("app.core.redis.get_redis", side_effect=Exception("Redis down")):
            # Should not raise
            await n._dead_letter("message", "error")
