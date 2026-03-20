"""Retry logic for transient failures."""
import asyncio
import functools
from collections.abc import Callable
from typing import TypeVar

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


async def retry_async(
    func: Callable,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
    **kwargs,
) -> T:
    """Retry an async function with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        exceptions: Tuple of exception types to retry on
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
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
