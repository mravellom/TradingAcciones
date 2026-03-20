from unittest.mock import patch

import pytest

from app.core.security import verify_api_key
from fastapi import HTTPException


class TestApiKeyAuth:
    @pytest.mark.asyncio
    async def test_no_key_configured_allows_all(self):
        """Dev mode: no API key configured = auth disabled."""
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.api_key = ""
            result = await verify_api_key(api_key=None)
            assert result == "dev-mode"

    @pytest.mark.asyncio
    async def test_valid_key(self):
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.api_key = "my-secret-key"
            result = await verify_api_key(api_key="my-secret-key")
            assert result == "my-secret-key"

    @pytest.mark.asyncio
    async def test_missing_key_when_configured(self):
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.api_key = "my-secret-key"
            with pytest.raises(HTTPException) as exc:
                await verify_api_key(api_key=None)
            assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_key(self):
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.api_key = "my-secret-key"
            with pytest.raises(HTTPException) as exc:
                await verify_api_key(api_key="wrong-key")
            assert exc.value.status_code == 403
