"""Tests for BinanceExecutor retry and reconciliation logic.

Validates:
- Retry on transient error then success
- Non-retryable error skips retry and raises immediately
- Reconciliation finds filled order after timeout
- Reconciliation returns None when order not found on Binance
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.enums import ExecutionMode, OrderSide
from app.pipeline.execution.base import Fill
from app.pipeline.execution.binance_executor import BinanceExecutor


def _mock_binance_api_exception(code: int, message: str = "error"):
    """Create a mock BinanceAPIException."""
    exc = MagicMock()
    exc.code = code
    exc.message = message
    exc.__class__.__name__ = "BinanceAPIException"

    from binance.exceptions import BinanceAPIException as RealExc
    real_exc = RealExc(None, code, message)
    return real_exc


def _make_binance_fill_response(**overrides):
    """Create a mock Binance order response."""
    return {
        "orderId": overrides.get("orderId", "12345"),
        "status": overrides.get("status", "FILLED"),
        "executedQty": overrides.get("executedQty", "0.1"),
        "cummulativeQuoteQty": overrides.get("cummulativeQuoteQty", "5000"),
        "fills": overrides.get("fills", [
            {"qty": "0.1", "price": "50000.00"},
        ]),
    }


@pytest.mark.asyncio
async def test_retry_on_transient_error_then_success():
    """Transient Binance error should be retried and succeed on next attempt."""
    from binance.exceptions import BinanceAPIException

    executor = BinanceExecutor()
    mock_client = AsyncMock()
    executor._client = mock_client

    # First call: transient error (-1003 = rate limit)
    # Second call: success
    transient_exc = BinanceAPIException(None, -1003, "Too many requests")
    mock_client.create_order.side_effect = [
        transient_exc,
        _make_binance_fill_response(),
    ]

    order_id = uuid4()

    with patch("app.pipeline.execution.binance_executor.binance_rate_limiter") as rl:
        rl.check = AsyncMock()
        with patch("app.core.retry.asyncio.sleep", new_callable=AsyncMock):
            fill = await executor.submit(
                order_id=order_id,
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.1"),
                price=Decimal("50000"),
            )

    assert isinstance(fill, Fill)
    assert fill.order_id == order_id
    assert fill.symbol == "BTCUSDT"
    assert mock_client.create_order.call_count == 2


@pytest.mark.asyncio
async def test_non_retryable_error_raises_immediately():
    """Non-retryable errors (e.g. insufficient balance -2010) should not retry."""
    from binance.exceptions import BinanceAPIException

    executor = BinanceExecutor()
    mock_client = AsyncMock()
    executor._client = mock_client

    # -2010 = Insufficient balance (non-retryable)
    non_retryable = BinanceAPIException(None, -2010, "Insufficient balance")
    mock_client.create_order.side_effect = non_retryable

    # reconcile_order should also be attempted, mock it to return None
    mock_client.get_order.side_effect = BinanceAPIException(None, -2013, "Order does not exist")

    order_id = uuid4()

    with patch("app.pipeline.execution.binance_executor.binance_rate_limiter") as rl:
        rl.check = AsyncMock()
        with patch("app.core.retry.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(BinanceAPIException) as exc_info:
                await executor.submit(
                    order_id=order_id,
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    quantity=Decimal("0.1"),
                    price=Decimal("50000"),
                )

    assert exc_info.value.code == -2010
    # Should have only called create_order once (no retry)
    assert mock_client.create_order.call_count == 1


@pytest.mark.asyncio
async def test_reconciliation_finds_filled_order():
    """After timeout, reconciliation should find a filled order on Binance."""
    from binance.exceptions import BinanceAPIException

    executor = BinanceExecutor()
    mock_client = AsyncMock()
    executor._client = mock_client

    order_id = uuid4()
    client_order_id = f"TP-{order_id.hex[:20]}"

    mock_client.get_order.return_value = {
        "orderId": "99999",
        "status": "FILLED",
        "executedQty": "0.1",
        "cummulativeQuoteQty": "5010.00",
    }

    fill = await executor.reconcile_order(
        order_id=order_id,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        client_order_id=client_order_id,
        expected_price=Decimal("50000"),
    )

    assert fill is not None
    assert fill.order_id == order_id
    assert fill.exchange_order_id == "99999"
    assert fill.execution_mode == ExecutionMode.LIVE
    assert fill.quantity == Decimal("0.10000000")
    # avg_price = 5010 / 0.1 = 50100
    assert fill.price == Decimal("50100.00000000")


@pytest.mark.asyncio
async def test_reconciliation_returns_none_order_not_found():
    """Reconciliation should return None when order doesn't exist on Binance."""
    from binance.exceptions import BinanceAPIException

    executor = BinanceExecutor()
    mock_client = AsyncMock()
    executor._client = mock_client

    # -2013 = Order does not exist
    mock_client.get_order.side_effect = BinanceAPIException(None, -2013, "Order does not exist")

    order_id = uuid4()
    client_order_id = f"TP-{order_id.hex[:20]}"

    fill = await executor.reconcile_order(
        order_id=order_id,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        client_order_id=client_order_id,
        expected_price=Decimal("50000"),
    )

    assert fill is None
