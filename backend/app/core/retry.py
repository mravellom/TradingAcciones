"""Retry logic for transient failures."""
import asyncio
import functools
from collections.abc import Callable
from typing import TypeVar

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# Binance error codes that should NOT be retried (permanent failures)
NON_RETRYABLE_BINANCE_CODES = {
    -2010,  # Insufficient balance
    -1013,  # Invalid quantity
    -1021,  # Timestamp outside recvWindow
    -1102,  # Mandatory parameter missing
    -1116,  # Invalid orderType
    -2015,  # Invalid API-key, IP, or permissions
}


def is_retryable_binance_error(exc: Exception) -> bool:
    """Check if a Binance exception is retryable (transient)."""
    try:
        from binance.exceptions import BinanceAPIException
        if isinstance(exc, BinanceAPIException):
            return exc.code not in NON_RETRYABLE_BINANCE_CODES
    except ImportError:
        pass
    # Network errors, timeouts are always retryable
    return True


async def retry_async(
    func: Callable,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
    should_retry: Callable[[Exception], bool] | None = None,
    **kwargs,
) -> T:
    """Retry an async function with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        exceptions: Tuple of exception types to retry on
        should_retry: Optional callback to decide if a specific exception is retryable.
                      If it returns False, the exception is raised immediately.
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            last_exception = e

            # Check if this specific exception should be retried
            if should_retry is not None and not should_retry(e):
                logger.error(
                    "retry_non_retryable",
                    func=func.__name__,
                    error=str(e),
                )
                raise

            if attempt == max_retries:
                logger.error(
                    "retry_exhausted",
                    func=func.__name__,
                    attempts=attempt + 1,
                    error=str(e),
                )
                raise

            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning(
                "retry_attempt",
                func=func.__name__,
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=delay,
                error=str(e),
            )
            await asyncio.sleep(delay)

    raise last_exception  # Should never reach here
