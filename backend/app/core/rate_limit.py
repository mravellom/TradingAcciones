"""Redis-based rate limiter.

Uses sliding window counter pattern.
Applied as FastAPI dependency on endpoints.
"""
from fastapi import HTTPException, Request, status

from app.config import settings
from app.core.redis import get_redis


class RateLimiter:
    """Sliding window rate limiter backed by Redis."""

    def __init__(
        self,
        max_requests: int | None = None,
        window_seconds: int | None = None,
        key_prefix: str = "ratelimit",
    ):
        self._max_requests = max_requests or settings.rate_limit_requests
        self._window = window_seconds or settings.rate_limit_window_seconds
        self._prefix = key_prefix

    async def check(self, identifier: str) -> None:
        """Check rate limit for an identifier. Raises 429 if exceeded."""
        redis = get_redis()
        key = f"{self._prefix}:{identifier}"

        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, self._window)

        if current > self._max_requests:
            ttl = await redis.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {ttl}s.",
                headers={"Retry-After": str(ttl)},
            )


# Default limiter instance
default_limiter = RateLimiter()


async def rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency that applies rate limiting per client IP."""
    client_ip = request.client.host if request.client else "unknown"
    await default_limiter.check(client_ip)


class BinanceRateLimiter:
    """Tracks Binance API rate limits.

    Binance limits: 1200 requests/minute for REST API.
    """

    def __init__(self, max_requests: int = 1100, window_seconds: int = 60):
        self._limiter = RateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
            key_prefix="binance_ratelimit",
        )

    async def check(self) -> None:
        """Check if we can make another Binance API call."""
        await self._limiter.check("binance_api")

    async def get_usage(self) -> dict:
        """Get current rate limit usage."""
        redis = get_redis()
        key = "binance_ratelimit:binance_api"
        current = await redis.get(key)
        ttl = await redis.ttl(key)
        return {
            "current_requests": int(current) if current else 0,
            "max_requests": self._limiter._max_requests,
            "window_reset_seconds": max(ttl, 0),
        }


binance_rate_limiter = BinanceRateLimiter()
