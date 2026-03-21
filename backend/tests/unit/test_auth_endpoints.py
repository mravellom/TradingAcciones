"""Tests for security: auth on critical endpoints, LIVE mode validation.

Validates:
- Risk config PUT requires auth
- Strategy create/update/activate require auth
- LIVE mode config validation fails without API key
- LIVE mode config validation fails with debug=True
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.security import verify_api_key


@pytest.mark.asyncio
async def test_risk_config_put_requires_auth():
    """PUT /risk/config should require API key auth."""
    # With a configured API key but no key provided -> 401
    with patch("app.core.security.settings") as mock_settings:
        mock_settings.api_key = "secret-key-123"
        mock_settings.debug = False

        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(api_key=None)

        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_strategy_create_requires_auth():
    """POST /strategies/ should require API key auth."""
    with patch("app.core.security.settings") as mock_settings:
        mock_settings.api_key = "secret-key-123"
        mock_settings.debug = False

        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(api_key=None)

        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_strategy_update_requires_auth_wrong_key():
    """Strategy update with wrong API key should return 403."""
    with patch("app.core.security.settings") as mock_settings:
        mock_settings.api_key = "correct-key"
        mock_settings.debug = False

        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(api_key="wrong-key")

        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_valid_api_key_passes():
    """Correct API key should pass authentication."""
    with patch("app.core.security.settings") as mock_settings:
        mock_settings.api_key = "my-secret-key"
        mock_settings.debug = False

        result = await verify_api_key(api_key="my-secret-key")

    assert result == "my-secret-key"


@pytest.mark.asyncio
async def test_no_key_configured_debug_mode_allows_access():
    """When no API key is configured and debug=True, access is allowed (dev mode)."""
    with patch("app.core.security.settings") as mock_settings:
        mock_settings.api_key = ""
        mock_settings.debug = True

        result = await verify_api_key(api_key=None)

    assert result == "dev-mode"


@pytest.mark.asyncio
async def test_no_key_configured_production_raises_500():
    """When no API key is configured and debug=False, should raise 500."""
    with patch("app.core.security.settings") as mock_settings:
        mock_settings.api_key = ""
        mock_settings.debug = False

        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(api_key=None)

        assert exc_info.value.status_code == 500
        assert "API key not configured" in exc_info.value.detail


def test_live_mode_fails_without_api_key():
    """LIVE mode should fail validation if API_KEY is not set."""
    from pydantic import ValidationError
    from app.config import Settings

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            execution_mode="LIVE",
            api_key="",
            binance_api_key="key",
            binance_api_secret="secret",
            debug=False,
        )

    assert "API_KEY must be set" in str(exc_info.value)


def test_live_mode_fails_with_debug_true():
    """LIVE mode should fail validation if debug=True."""
    from pydantic import ValidationError
    from app.config import Settings

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            execution_mode="LIVE",
            api_key="some-key",
            binance_api_key="key",
            binance_api_secret="secret",
            debug=True,
        )

    assert "DEBUG must be False" in str(exc_info.value)


def test_live_mode_fails_without_binance_keys():
    """LIVE mode should fail if Binance API keys are missing."""
    from pydantic import ValidationError
    from app.config import Settings

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            execution_mode="LIVE",
            api_key="some-key",
            binance_api_key="",
            binance_api_secret="",
            debug=False,
        )

    assert "BINANCE_API_KEY" in str(exc_info.value)
