"""Tests for ApprovalExecutor — verifies it delegates to TradingPipeline."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.enums import ExecutionMode, OrderStatus
from app.models.order import Order
from app.tasks.approval_executor import ApprovalExecutor


def _make_executor():
    """Build an ApprovalExecutor with all dependencies mocked."""
    executor = MagicMock()
    executor.mode = ExecutionMode.PAPER

    guard = AsyncMock()
    market_data = AsyncMock()
    market_data.get_market_snapshot.return_value = {
        "price": Decimal("42000"),
        "bid": Decimal("41999"),
        "ask": Decimal("42001"),
        "volume_24h": Decimal("500000"),
        "asset_class": "CRYPTO",
    }

    session_factory = AsyncMock()

    with patch("app.tasks.approval_executor.get_redis", return_value=AsyncMock()):
        approval_exec = ApprovalExecutor(
            executor=executor,
            guard=guard,
            market_data=market_data,
            session_factory=session_factory,
        )

    return approval_exec


def _make_order(**overrides):
    order = MagicMock(spec=Order)
    order.id = overrides.get("id", uuid4())
    order.symbol = overrides.get("symbol", "BTCUSDT")
    order.side = overrides.get("side", "BUY")
    order.asset_class = overrides.get("asset_class", "CRYPTO")
    order.requested_qty = overrides.get("requested_qty", Decimal("0.01"))
    order.requested_price = overrides.get("requested_price", Decimal("42000"))
    order.stop_loss = overrides.get("stop_loss", Decimal("41000"))
    order.take_profit = overrides.get("take_profit", Decimal("44000"))
    order.signal_id = overrides.get("signal_id", uuid4())
    order.execution_mode = overrides.get("execution_mode", "PAPER")
    order.status = OrderStatus.SUBMITTED.value
    order.exchange_order_id = None
    order.created_at = None
    return order


class TestApprovalExecutorDelegation:
    """Verify ApprovalExecutor delegates to TradingPipeline."""

    @pytest.mark.asyncio
    async def test_execute_order_delegates_to_pipeline(self):
        approval_exec = _make_executor()
        order = _make_order()
        session = AsyncMock()

        mock_result = MagicMock()
        mock_result.action = "EXECUTED"
        mock_result.reason = ""

        with patch(
            "app.tasks.approval_executor.TradingPipeline"
        ) as MockPipeline:
            mock_pipeline = AsyncMock()
            mock_pipeline.execute_approved_order.return_value = mock_result
            MockPipeline.return_value = mock_pipeline

            await approval_exec._execute_order(session, order)

        mock_pipeline.execute_approved_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_market_data_failure_rejects_order(self):
        approval_exec = _make_executor()
        approval_exec._market_data.get_market_snapshot.side_effect = Exception(
            "API timeout"
        )
        order = _make_order()
        session = AsyncMock()

        await approval_exec._execute_order(session, order)

        assert order.status == OrderStatus.REJECTED.value

    @pytest.mark.asyncio
    async def test_poll_cycle_skips_when_halted(self):
        approval_exec = _make_executor()
        approval_exec._redis.get = AsyncMock(return_value="HALTED")

        # Should not query for orders
        await approval_exec._poll_cycle()

        approval_exec._session_factory.assert_not_called()
