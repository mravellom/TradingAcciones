"""Tests for AlpacaExecutor."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.enums import ExecutionMode, OrderSide
from app.pipeline.execution.alpaca_executor import AlpacaExecutor


class TestAlpacaExecutor:
    def test_paper_mode_by_default(self):
        executor = AlpacaExecutor()
        assert executor.mode == ExecutionMode.PAPER

    def test_paper_mode_explicit(self):
        executor = AlpacaExecutor(paper_mode=True)
        assert executor.mode == ExecutionMode.PAPER

    def test_live_mode(self):
        executor = AlpacaExecutor(paper_mode=False)
        assert executor.mode == ExecutionMode.LIVE

    @pytest.mark.asyncio
    async def test_paper_submit_delegates_to_paper_engine(self):
        executor = AlpacaExecutor(paper_mode=True)
        mock_fill = AsyncMock()
        executor._paper_engine.submit = mock_fill

        order_id = uuid4()
        await executor.submit(
            order_id=order_id,
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            price=Decimal("150.00"),
        )

        mock_fill.assert_called_once_with(
            order_id, "AAPL", OrderSide.BUY, Decimal("10"), Decimal("150.00")
        )

    @pytest.mark.asyncio
    async def test_paper_cancel_returns_true(self):
        executor = AlpacaExecutor(paper_mode=True)
        result = await executor.cancel(uuid4())
        assert result is True

    @pytest.mark.asyncio
    @patch("app.pipeline.execution.alpaca_executor.is_us_market_open", return_value=True)
    async def test_live_submit_requires_connection(self, mock_mh):
        executor = AlpacaExecutor(paper_mode=False)
        with pytest.raises(RuntimeError, match="not connected"):
            await executor.submit(
                uuid4(), "AAPL", OrderSide.BUY, Decimal("10"), Decimal("150")
            )

    @pytest.mark.asyncio
    async def test_live_cancel_without_client_returns_false(self):
        executor = AlpacaExecutor(paper_mode=False)
        result = await executor.cancel(uuid4(), "some-id")
        assert result is False

    def test_paper_engine_has_stock_slippage(self):
        executor = AlpacaExecutor(paper_mode=True)
        # Stock slippage should be 0.01% (tighter than crypto 0.05%)
        assert executor._paper_engine._slippage_pct == Decimal("0.0001")
