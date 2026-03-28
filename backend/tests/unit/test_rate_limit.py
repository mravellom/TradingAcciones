from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.core.rate_limit import RateLimiter, rate_limit_dependency
from fastapi import HTTPException


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_request_within_limit_passes(self):
        """Requests under the limit should succeed."""
        mock_redis = AsyncMock()
        mock_redis.incr.return_value = 1
        mock_redis.expire.return_value = True

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            limiter = RateLimiter(max_requests=10, window_seconds=60)
            # Should not raise
            await limiter.check("test-client")

        mock_redis.incr.assert_called_once()
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_at_limit_passes(self):
        """Request exactly at the limit should still pass."""
        mock_redis = AsyncMock()
        mock_redis.incr.return_value = 10

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            limiter = RateLimiter(max_requests=10, window_seconds=60)
            await limiter.check("test-client")

    @pytest.mark.asyncio
    async def test_request_exceeding_limit_raises_429(self):
        """Requests over the limit should raise 429."""
        mock_redis = AsyncMock()
        mock_redis.incr.return_value = 11
        mock_redis.ttl.return_value = 45

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            limiter = RateLimiter(max_requests=10, window_seconds=60)
            with pytest.raises(HTTPException) as exc:
                await limiter.check("test-client")

            assert exc.value.status_code == 429
            assert "Retry-After" in exc.value.headers
            assert exc.value.headers["Retry-After"] == "45"

    @pytest.mark.asyncio
    async def test_first_request_sets_expiry(self):
        """First request (incr returns 1) should set TTL on the key."""
        mock_redis = AsyncMock()
        mock_redis.incr.return_value = 1

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            limiter = RateLimiter(max_requests=10, window_seconds=120)
            await limiter.check("new-client")

        mock_redis.expire.assert_called_once_with("ratelimit:new-client", 120)

    @pytest.mark.asyncio
    async def test_subsequent_request_does_not_reset_expiry(self):
        """Subsequent requests should not reset the TTL."""
        mock_redis = AsyncMock()
        mock_redis.incr.return_value = 5

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            limiter = RateLimiter(max_requests=10, window_seconds=60)
            await limiter.check("existing-client")

        mock_redis.expire.assert_not_called()


class TestRateLimitDependency:
    @pytest.mark.asyncio
    async def test_dependency_extracts_client_ip(self):
        """The dependency should use the client IP as the rate limit key."""
        mock_redis = AsyncMock()
        mock_redis.incr.return_value = 1

        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.100"

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            await rate_limit_dependency(mock_request)

        mock_redis.incr.assert_called_once_with("ratelimit:192.168.1.100")

    @pytest.mark.asyncio
    async def test_dependency_unknown_client(self):
        """When client is None, should use 'unknown' as identifier."""
        mock_redis = AsyncMock()
        mock_redis.incr.return_value = 1

        mock_request = MagicMock()
        mock_request.client = None

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            await rate_limit_dependency(mock_request)

        mock_redis.incr.assert_called_once_with("ratelimit:unknown")
