from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.domain.enums import ExecutionMode, OrderSide
from app.pipeline.execution.paper_engine import PaperEngine


class TestPaperEngine:
    @pytest.fixture
    def engine(self):
        pe = PaperEngine(
            slippage_pct=Decimal("0.001"),  # 0.1% for predictable tests
            simulate_latency=False,  # No delay in tests
        )
        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        pe._redis = mock_redis
        return pe

    @pytest.mark.asyncio
    async def test_mode_is_paper(self, engine):
        assert engine.mode == ExecutionMode.PAPER

    @pytest.mark.asyncio
    async def test_buy_fill_has_positive_slippage(self, engine):
        fill = await engine.submit(
            order_id=uuid4(),
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("42000"),
        )
        assert fill.price > Decimal("42000")  # BUY slippage increases price
        assert fill.quantity == Decimal("0.1")
        assert fill.execution_mode == ExecutionMode.PAPER
        assert fill.exchange_order_id.startswith("PAPER-")
        assert fill.slippage > 0

    @pytest.mark.asyncio
    async def test_sell_fill_has_negative_slippage(self, engine):
        fill = await engine.submit(
            order_id=uuid4(),
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("0.5"),
            price=Decimal("42000"),
        )
        assert fill.price < Decimal("42000")  # SELL slippage decreases price

    @pytest.mark.asyncio
    async def test_uses_cached_price(self, engine):
        engine._redis.hgetall = AsyncMock(return_value={
            "price": "43000",
            "bid": "42990",
            "ask": "43010",
            "timestamp": "2026-01-01T00:00:00",
        })
        fill = await engine.submit(
            order_id=uuid4(),
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("42000"),  # Order price is 42000 but cache is 43000
        )
        # Should use cached price (43000) + slippage
        assert fill.price > Decimal("43000")

    @pytest.mark.asyncio
    async def test_cancel_always_succeeds(self, engine):
        result = await engine.cancel(uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_fill_has_timestamp(self, engine):
        fill = await engine.submit(
            order_id=uuid4(),
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("3000"),
        )
        assert fill.timestamp is not None
        assert fill.symbol == "ETHUSDT"
