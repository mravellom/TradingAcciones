"""API key authentication.

Protects critical endpoints (halt, resume, strategy mutations).
Read-only endpoints remain public for the dashboard.
"""
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: Annotated[str | None, Security(API_KEY_HEADER)] = None,
) -> str:
    """Verify the API key from the X-API-Key header.

    If no API key is configured in settings, authentication is disabled (dev mode).
    """
    configured_key = settings.api_key

    # No key configured: only allow in debug mode
    if not configured_key:
        if not settings.debug:
            logger.error("api_key_not_configured_in_production")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="API key not configured. Set API_KEY in production.",
            )
        return "dev-mode"

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide X-API-Key header.",
        )

    if not secrets.compare_digest(api_key, configured_key):
        logger.warning("invalid_api_key_attempt")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    return api_key


# Dependency for protected routes
RequireAuth = Depends(verify_api_key)
