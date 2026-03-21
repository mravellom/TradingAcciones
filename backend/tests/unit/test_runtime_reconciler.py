"""Tests for the runtime reconciler — the critical safety net."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.enums import ExecutionMode, OrderSide, OrderStatus, PositionStatus


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_executor():
    executor = MagicMock()
    executor.mode = ExecutionMode.LIVE
    executor.client = AsyncMock()
    executor.reconcile_order = AsyncMock(return_value=None)
    executor.client.get_open_orders = AsyncMock(return_value=[])
    executor.client.get_account = AsyncMock(return_value={"balances": []})
    return executor


def _make_order(status="SUBMITTING", exchange_order_id=None, minutes_ago=10):
    order = MagicMock()
    order.id = uuid.uuid4()
    order.symbol = "BTCUSDT"
    order.side = "BUY"
    order.status = status
    order.execution_mode = ExecutionMode.LIVE.value
    order.exchange_order_id = exchange_order_id
    order.requested_price = Decimal("50000")
    order.requested_qty = Decimal("0.1")
    order.updated_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    order.created_at = order.updated_at
    return order


def _make_position(has_exchange_id=True):
    pos = MagicMock()
    pos.id = uuid.uuid4()
    pos.symbol = "BTCUSDT"
    pos.status = PositionStatus.OPEN.value
    pos.execution_mode = ExecutionMode.LIVE.value
    pos.entry_order_id = uuid.uuid4()
    pos.entry_price = Decimal("50000")
    pos.quantity = Decimal("0.1")
    return pos


class TestRuntimeReconcilerStuckOrders:
    """Test that stuck SUBMITTING orders are detected and reconciled."""

    @pytest.mark.asyncio
    @patch("app.tasks.runtime_reconciler.get_redis")
    async def test_stuck_order_found_on_binance_gets_filled(self, mock_get_redis, mock_session, mock_executor):
        """If Binance says order was filled, update local state."""
        from app.pipeline.execution.base import Fill
        from app.pipeline.execution.binance_executor import BinanceExecutor
        from app.tasks.runtime_reconciler import RuntimeReconciler

        # Make executor pass isinstance check
        mock_executor.__class__ = BinanceExecutor

        fill = Fill(
            order_id=uuid.uuid4(),
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50100"),
            quantity=Decimal("0.1"),
            timestamp=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.LIVE,
            exchange_order_id="12345",
            slippage=Decimal("100"),
        )
        mock_executor.reconcile_order = AsyncMock(return_value=fill)

        stuck_order = _make_order(status="SUBMITTING", minutes_ago=5)

        # Mock session.execute to return the stuck order
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck_order]
        mock_session.execute = AsyncMock(return_value=mock_result)

        reconciler = RuntimeReconciler(
            executor=mock_executor,
            session_factory=AsyncMock(),
        )

        issues = await reconciler._check_stuck_orders(mock_session)

        assert len(issues) == 1
        assert issues[0]["type"] == "STUCK_ORDER_RECONCILED"
        assert issues[0]["severity"] == "CRITICAL"
        assert stuck_order.status == OrderStatus.FILLED.value
        assert stuck_order.exchange_order_id == "12345"

    @pytest.mark.asyncio
    @patch("app.tasks.runtime_reconciler.get_redis")
    async def test_stuck_order_not_on_binance_gets_cancelled(self, mock_get_redis, mock_session, mock_executor):
        """If Binance doesn't know about the order, cancel it locally."""
        from app.pipeline.execution.binance_executor import BinanceExecutor
        from app.tasks.runtime_reconciler import RuntimeReconciler

        mock_executor.__class__ = BinanceExecutor
        mock_executor.reconcile_order = AsyncMock(return_value=None)

        stuck_order = _make_order(status="SUBMITTING", minutes_ago=5)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck_order]
        mock_session.execute = AsyncMock(return_value=mock_result)

        reconciler = RuntimeReconciler(
            executor=mock_executor,
            session_factory=AsyncMock(),
        )

        issues = await reconciler._check_stuck_orders(mock_session)

        assert len(issues) == 1
        assert issues[0]["type"] == "STUCK_ORDER_CANCELLED"
        assert stuck_order.status == OrderStatus.CANCELLED.value


class TestRuntimeReconcilerPositions:
    """Test position vs exchange verification."""

    @pytest.mark.asyncio
    @patch("app.tasks.runtime_reconciler.get_redis")
    async def test_position_without_exchange_order_detected(self, mock_get_redis, mock_session, mock_executor):
        from app.tasks.runtime_reconciler import RuntimeReconciler

        pos = _make_position()
        order = _make_order(status="FILLED", exchange_order_id=None)

        # First execute returns positions, session.get returns order
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [pos]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=order)

        reconciler = RuntimeReconciler(
            executor=mock_executor,
            session_factory=AsyncMock(),
        )

        issues = await reconciler._check_positions_vs_exchange(mock_session)

        assert len(issues) == 1
        assert issues[0]["type"] == "POSITION_NO_EXCHANGE_ORDER"
        assert issues[0]["severity"] == "CRITICAL"

    @pytest.mark.asyncio
    @patch("app.tasks.runtime_reconciler.get_redis")
    async def test_position_with_exchange_order_is_clean(self, mock_get_redis, mock_session, mock_executor):
        from app.tasks.runtime_reconciler import RuntimeReconciler

        pos = _make_position()
        order = _make_order(status="FILLED", exchange_order_id="12345")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [pos]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=order)

        reconciler = RuntimeReconciler(
            executor=mock_executor,
            session_factory=AsyncMock(),
        )

        issues = await reconciler._check_positions_vs_exchange(mock_session)
        assert len(issues) == 0


class TestRuntimeReconcilerHalt:
    """Test that critical issues trigger system halt."""

    @pytest.mark.asyncio
    @patch("app.tasks.runtime_reconciler.get_redis")
    async def test_critical_issue_halts_system(self, mock_get_redis, mock_session, mock_executor):
        from app.tasks.runtime_reconciler import RuntimeReconciler

        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        reconciler = RuntimeReconciler(
            executor=mock_executor,
            session_factory=AsyncMock(),
        )
        reconciler._redis = mock_redis

        critical_issues = [{
            "type": "STUCK_ORDER_RECONCILED",
            "severity": "CRITICAL",
            "order_id": str(uuid.uuid4()),
            "symbol": "BTCUSDT",
            "action": "test action",
            "fill_price": "50000",
            "fill_qty": "0.1",
        }]

        event_repo_mock = AsyncMock()
        with patch("app.tasks.runtime_reconciler.EventRepository", return_value=event_repo_mock):
            await reconciler._handle_issues(mock_session, critical_issues)

        # Should have halted the system
        mock_redis.set.assert_called_with("system:status", "HALTED")
