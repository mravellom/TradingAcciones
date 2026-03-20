from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.enums import ExecutionMode, OrderSide
from app.pipeline.execution.binance_executor import BinanceExecutor


class TestBinanceExecutor:
    def test_mode_is_live(self):
        executor = BinanceExecutor()
        assert executor.mode == ExecutionMode.LIVE

    @pytest.mark.asyncio
    async def test_not_connected_raises(self):
        executor = BinanceExecutor()
        with pytest.raises(RuntimeError, match="not connected"):
            _ = executor.client

    @pytest.mark.asyncio
    async def test_submit_parses_fills(self):
        executor = BinanceExecutor()
        executor._client = AsyncMock()
        executor._client.create_order = AsyncMock(return_value={
            "orderId": "12345",
            "status": "FILLED",
            "executedQty": "0.1",
            "fills": [
                {"price": "42010.00", "qty": "0.06"},
                {"price": "42020.00", "qty": "0.04"},
            ],
        })

        with patch("app.pipeline.execution.binance_executor.binance_rate_limiter") as mock_rl:
            mock_rl.check = AsyncMock()

            fill = await executor.submit(
                order_id=uuid4(),
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.1"),
                price=Decimal("42000"),
            )

        assert fill.execution_mode == ExecutionMode.LIVE
        assert fill.exchange_order_id == "12345"
        assert fill.quantity == Decimal("0.10000000")
        # Weighted avg: (42010*0.06 + 42020*0.04) / 0.1 = 42014
        assert fill.price == Decimal("42014.00000000")

    @pytest.mark.asyncio
    async def test_cancel_returns_false_without_exchange_id(self):
        executor = BinanceExecutor()
        result = await executor.cancel(uuid4(), exchange_order_id="")
        assert result is False
