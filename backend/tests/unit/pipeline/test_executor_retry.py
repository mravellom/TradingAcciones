"""Tests for BinanceExecutor retry and reconciliation logic."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.enums import ExecutionMode, OrderSide
from app.pipeline.execution.base import Fill
from app.pipeline.execution.binance_executor import BinanceExecutor


def _make_binance_exc(code: int, message: str = "error"):
    """Create a BinanceAPIException with a mock response and correct code."""
    from binance.exceptions import BinanceAPIException
    import json

    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = json.dumps({"code": code, "msg": message})
    mock_response.json.return_value = {"code": code, "msg": message}

    exc = BinanceAPIException(mock_response, code, message)
    # Ensure code is set correctly (library may parse differently)
    exc.code = code
    exc.message = message
    return exc


def _make_binance_fill_response(**overrides):
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
    """Transient Binance error should be retried and succeed."""
    executor = BinanceExecutor()
    mock_client = AsyncMock()
    executor._client = mock_client

    transient_exc = _make_binance_exc(-1003, "Too many requests")
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
    assert mock_client.create_order.call_count == 2


@pytest.mark.asyncio
async def test_non_retryable_error_raises_immediately():
    """Non-retryable errors should not retry."""
    from binance.exceptions import BinanceAPIException

    executor = BinanceExecutor()
    mock_client = AsyncMock()
    executor._client = mock_client

    non_retryable = _make_binance_exc(-2010, "Insufficient balance")
    mock_client.create_order.side_effect = non_retryable

    # reconcile_order should return None (order not on exchange)
    not_found_exc = _make_binance_exc(-2013, "Order does not exist")
    mock_client.get_order.side_effect = not_found_exc

    order_id = uuid4()

    with patch("app.pipeline.execution.binance_executor.binance_rate_limiter") as rl:
        rl.check = AsyncMock()
        with patch("app.core.retry.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(BinanceAPIException):
                await executor.submit(
                    order_id=order_id,
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    quantity=Decimal("0.1"),
                    price=Decimal("50000"),
                )

    # Should have only tried once (no retry for non-retryable)
    assert mock_client.create_order.call_count == 1


@pytest.mark.asyncio
async def test_reconciliation_finds_filled_order():
    """After timeout, reconciliation should find a filled order on Binance."""
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
    assert fill.exchange_order_id == "99999"
    assert fill.quantity == Decimal("0.10000000")


@pytest.mark.asyncio
async def test_reconciliation_returns_none_order_not_found():
    """Reconciliation returns None when order doesn't exist on Binance."""
    executor = BinanceExecutor()
    mock_client = AsyncMock()
    executor._client = mock_client

    not_found = _make_binance_exc(-2013, "Order does not exist")
    mock_client.get_order.side_effect = not_found

    order_id = uuid4()

    fill = await executor.reconcile_order(
        order_id=order_id,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        client_order_id=f"TP-{order_id.hex[:20]}",
        expected_price=Decimal("50000"),
    )

    assert fill is None
