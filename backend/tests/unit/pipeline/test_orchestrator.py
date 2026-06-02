"""Critical tests for TradingPipeline orchestrator.

Tests SL/TP validation, balance checks, and pipeline flow logic.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.domain.enums import (
    ExecutionMode,
    OrderSide,
    OrderStatus,
    RiskAction,
    SignalType,
)
from app.pipeline.capital_manager.capital_manager import Sizing
from app.pipeline.execution.base import Fill
from app.pipeline.execution.guard import GuardResult, MarketSnapshot
from app.pipeline.orchestrator import PipelineResult, TradingPipeline, _validate_sl_tp
from app.pipeline.risk_manager.rules.base import RiskDecision
from app.pipeline.strategy.base import TradeIntent


# ── Helpers ──


def _intent(**overrides) -> TradeIntent:
    defaults = dict(
        symbol="BTCUSDT",
        action=SignalType.BUY,
        confidence=Decimal("0.75"),
        entry_price=Decimal("42000"),
        stop_loss=Decimal("41000"),
        take_profit=Decimal("44000"),
        strategy_id=uuid4(),
        timeframe="1h",
        indicators={"rsi": 28},
    )
    defaults.update(overrides)
    return TradeIntent(**defaults)


def _market(**overrides) -> MarketSnapshot:
    defaults = dict(
        symbol="BTCUSDT",
        price=Decimal("42000"),
        bid=Decimal("41999"),
        ask=Decimal("42001"),
        volume_24h=Decimal("500000"),
        asset_class="CRYPTO",
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def _fill(order_id: UUID | None = None, **overrides) -> Fill:
    defaults = dict(
        order_id=order_id or uuid4(),
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal("42000"),
        quantity=Decimal("0.01"),
        timestamp=datetime.now(timezone.utc),
        execution_mode=ExecutionMode.PAPER,
        exchange_order_id="PAPER-001",
        slippage=Decimal("0.001"),
    )
    defaults.update(overrides)
    return Fill(**defaults)


def _portfolio_mock(
    available=Decimal("10000"),
    total=Decimal("10000"),
    daily_pnl=Decimal("0"),
    max_drawdown=Decimal("0"),
    mode="PAPER",
):
    p = MagicMock()
    p.total_balance = total
    p.available_balance = available
    p.daily_pnl = daily_pnl
    p.max_drawdown = max_drawdown
    p.execution_mode = mode
    return p


def _position_mock():
    pos = MagicMock()
    pos.id = uuid4()
    pos.oco_order_id = None
    return pos


class _FakeSignal:
    """Mimics a flushed Signal ORM object."""

    def __init__(self):
        self.id = uuid4()


class _FakeOrder:
    """Mimics a flushed Order ORM object with settable attributes."""

    def __init__(self):
        self.id = uuid4()
        self.status = None
        self.filled_qty = None
        self.avg_fill_price = None
        self.exchange_order_id = None
        self.side = "BUY"


def _build_pipeline(
    risk_decision=None,
    sizing=None,
    guard_result=None,
    fill=None,
    portfolio=None,
    position=None,
    system_status="RUNNING",
    open_count=0,
    symbol_exposure=Decimal("0"),
):
    """Build a TradingPipeline with all dependencies mocked."""

    # Core mocks
    risk_manager = AsyncMock()
    risk_manager.validate = AsyncMock(
        return_value=risk_decision or RiskDecision.approve("all_rules")
    )
    risk_manager._rules = [MagicMock(), MagicMock()]  # 2 rules

    capital_manager = MagicMock()
    capital_manager.calculate_size = MagicMock(
        return_value=sizing
        if sizing is not None
        else Sizing(
            quantity=Decimal("0.01"),
            risk_amount=Decimal("100"),
            position_value=Decimal("420"),
        )
    )

    execution_guard = AsyncMock()
    execution_guard.validate = AsyncMock(
        return_value=guard_result or GuardResult.approve()
    )

    executor = AsyncMock()
    executor.mode = ExecutionMode.PAPER
    default_fill = fill or _fill()
    executor.submit = AsyncMock(return_value=default_fill)

    session = AsyncMock()
    session.add = MagicMock()

    # Track flush calls to assign IDs to signal/order
    _fake_signal = _FakeSignal()
    _fake_order = _FakeOrder()
    _flush_count = {"count": 0}

    async def _fake_flush():
        _flush_count["count"] += 1

    session.flush = AsyncMock(side_effect=_fake_flush)
    session.commit = AsyncMock()

    # Mock SELECT FOR UPDATE query
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = portfolio or _portfolio_mock()
    session.execute = AsyncMock(return_value=mock_result)

    # Redis mock
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=system_status)

    # Build pipeline with mocks
    with (
        patch("app.pipeline.orchestrator.get_redis", return_value=redis_mock),
        patch(
            "app.pipeline.orchestrator.PositionManager"
        ) as MockPosMgr,
        patch("app.pipeline.orchestrator.TradeTracker") as MockTracker,
        patch("app.pipeline.orchestrator.EventRepository") as MockEventRepo,
        patch("app.pipeline.orchestrator.PositionRepository") as MockPosRepo,
    ):
        mock_pos_mgr = AsyncMock()
        mock_pos_mgr.open_position = AsyncMock(
            return_value=position or _position_mock()
        )
        MockPosMgr.return_value = mock_pos_mgr

        mock_tracker = AsyncMock()
        MockTracker.return_value = mock_tracker

        mock_event_repo = AsyncMock()
        MockEventRepo.return_value = mock_event_repo

        mock_pos_repo = AsyncMock()
        mock_pos_repo.count_open = AsyncMock(return_value=open_count)
        mock_pos_repo.get_total_exposure_by_symbol = AsyncMock(
            return_value=symbol_exposure
        )
        MockPosRepo.return_value = mock_pos_repo

        pipeline = TradingPipeline(
            risk_manager=risk_manager,
            capital_manager=capital_manager,
            execution_guard=execution_guard,
            executor=executor,
            session=session,
        )

    # Expose mocks for assertions
    pipeline._test_mocks = {
        "risk_manager": risk_manager,
        "capital_manager": capital_manager,
        "execution_guard": execution_guard,
        "executor": executor,
        "session": session,
        "redis": redis_mock,
        "position_mgr": mock_pos_mgr,
        "tracker": mock_tracker,
        "event_repo": mock_event_repo,
        "position_repo": mock_pos_repo,
    }

    return pipeline


# ── SL/TP Validation (CRITICAL) ──


class TestSLTPValidation:
    def test_valid_buy_sl_tp(self):
        intent = _intent(
            action=SignalType.BUY,
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
        )
        assert _validate_sl_tp(intent) is None

    def test_buy_sl_above_entry_rejected(self):
        """CRITICAL: prevents immediate SL trigger on BUY."""
        intent = _intent(
            action=SignalType.BUY,
            entry_price=Decimal("42000"),
            stop_loss=Decimal("43000"),
            take_profit=Decimal("44000"),
        )
        error = _validate_sl_tp(intent)
        assert error is not None
        assert "stop_loss" in error

    def test_buy_tp_below_entry_rejected(self):
        """CRITICAL: prevents immediate TP trigger on BUY."""
        intent = _intent(
            action=SignalType.BUY,
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"),
            take_profit=Decimal("40000"),
        )
        error = _validate_sl_tp(intent)
        assert error is not None
        assert "take_profit" in error

    def test_buy_sl_equal_entry_rejected(self):
        intent = _intent(
            action=SignalType.BUY,
            entry_price=Decimal("42000"),
            stop_loss=Decimal("42000"),
            take_profit=Decimal("44000"),
        )
        assert _validate_sl_tp(intent) is not None

    def test_valid_sell_sl_tp(self):
        intent = _intent(
            action=SignalType.SELL,
            entry_price=Decimal("42000"),
            stop_loss=Decimal("43000"),
            take_profit=Decimal("40000"),
        )
        assert _validate_sl_tp(intent) is None

    def test_sell_sl_below_entry_rejected(self):
        intent = _intent(
            action=SignalType.SELL,
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"),
            take_profit=Decimal("40000"),
        )
        assert _validate_sl_tp(intent) is not None

    def test_zero_price_rejected(self):
        intent = _intent(entry_price=Decimal("0"))
        error = _validate_sl_tp(intent)
        assert error is not None
        assert "positive" in error.lower()

    def test_negative_sl_rejected(self):
        intent = _intent(stop_loss=Decimal("-100"))
        assert _validate_sl_tp(intent) is not None

    def test_negative_tp_rejected(self):
        intent = _intent(take_profit=Decimal("-100"))
        assert _validate_sl_tp(intent) is not None


# ── Pipeline Result ──


class TestPipelineResult:
    def test_executed_result(self):
        r = PipelineResult(action="EXECUTED", order_id=uuid4(), position_id=uuid4())
        assert r.action == "EXECUTED"

    def test_rejected_result(self):
        r = PipelineResult(action="REJECTED", reason="Too risky")
        assert r.action == "REJECTED"
        assert "risky" in r.reason

    def test_halted_result(self):
        r = PipelineResult(action="SYSTEM_HALTED", reason="Drawdown exceeded")
        assert r.action == "SYSTEM_HALTED"


class TestTradeIntent:
    def test_intent_creation(self):
        intent = _intent()
        assert intent.symbol == "BTCUSDT"
        assert intent.action == SignalType.BUY
        assert intent.confidence == Decimal("0.75")
        assert intent.stop_loss < intent.entry_price
        assert intent.take_profit > intent.entry_price


# ── Pipeline Flow Tests ──


class TestPipelineHappyPath:
    """Test the complete execution flow when everything goes well."""

    @pytest.mark.asyncio
    async def test_full_execution_returns_executed(self):
        pipeline = _build_pipeline()
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            result = await pipeline.execute(intent, market)

        assert result.action == "EXECUTED"
        assert result.order_id is not None or result.details.get("correlation_id")
        assert "fill_price" in result.details
        assert "quantity" in result.details
        assert "slippage" in result.details
        assert "correlation_id" in result.details

    @pytest.mark.asyncio
    async def test_executor_submit_called_with_correct_args(self):
        pipeline = _build_pipeline()
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            await pipeline.execute(intent, market)

        executor = pipeline._test_mocks["executor"]
        executor.submit.assert_called_once()
        call_kwargs = executor.submit.call_args
        assert call_kwargs.kwargs["symbol"] == "BTCUSDT"
        assert call_kwargs.kwargs["side"] == OrderSide.BUY

    @pytest.mark.asyncio
    async def test_position_opened_after_fill(self):
        pipeline = _build_pipeline()
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            await pipeline.execute(intent, market)

        pos_mgr = pipeline._test_mocks["position_mgr"]
        pos_mgr.open_position.assert_called_once()

    @pytest.mark.asyncio
    async def test_portfolio_updated_after_fill(self):
        pipeline = _build_pipeline()
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False
            with patch(
                "app.pipeline.orchestrator.PortfolioService"
            ) as MockPortSvc:
                mock_svc = AsyncMock()
                MockPortSvc.return_value = mock_svc

                await pipeline.execute(intent, market)

                mock_svc.record_fill.assert_called_once()
                call_kwargs = mock_svc.record_fill.call_args
                assert call_kwargs.kwargs["already_locked"] is True

    @pytest.mark.asyncio
    async def test_tracker_records_all_events(self):
        pipeline = _build_pipeline()
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            await pipeline.execute(intent, market)

        tracker = pipeline._test_mocks["tracker"]
        tracker.record_risk_approved.assert_called_once()
        tracker.record_guard_approved.assert_called_once()
        tracker.record_order_submitted.assert_called_once()
        tracker.record_order_filled.assert_called_once()

    @pytest.mark.asyncio
    async def test_sell_intent_sets_correct_side(self):
        pipeline = _build_pipeline()
        intent = _intent(
            action=SignalType.SELL,
            entry_price=Decimal("42000"),
            stop_loss=Decimal("43000"),
            take_profit=Decimal("40000"),
        )
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            await pipeline.execute(intent, market)

        executor = pipeline._test_mocks["executor"]
        call_kwargs = executor.submit.call_args
        assert call_kwargs.kwargs["side"] == OrderSide.SELL


class TestSystemHalted:
    """Test system status check (step 1)."""

    @pytest.mark.asyncio
    async def test_halted_system_returns_system_halted(self):
        pipeline = _build_pipeline(system_status="HALTED")
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            result = await pipeline.execute(intent, market)

        assert result.action == "SYSTEM_HALTED"
        assert "HALTED" in result.reason

    @pytest.mark.asyncio
    async def test_halted_system_does_not_call_risk_manager(self):
        pipeline = _build_pipeline(system_status="HALTED")
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            await pipeline.execute(intent, market)

        pipeline._test_mocks["risk_manager"].validate.assert_not_called()

    @pytest.mark.asyncio
    async def test_paused_system_returns_system_halted(self):
        pipeline = _build_pipeline(system_status="PAUSED")
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            result = await pipeline.execute(intent, market)

        assert result.action == "SYSTEM_HALTED"


class TestRiskManagerDecisions:
    """Test risk manager reject and halt paths (step 3)."""

    @pytest.mark.asyncio
    async def test_risk_reject_returns_rejected(self):
        decision = RiskDecision.reject("max_positions", "Too many open positions")
        pipeline = _build_pipeline(risk_decision=decision)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            result = await pipeline.execute(intent, market)

        assert result.action == "REJECTED"
        assert "max_positions" in result.reason
        assert "Too many open positions" in result.reason

    @pytest.mark.asyncio
    async def test_risk_reject_records_event(self):
        decision = RiskDecision.reject("daily_loss", "Daily loss limit")
        pipeline = _build_pipeline(risk_decision=decision)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            await pipeline.execute(intent, market)

        tracker = pipeline._test_mocks["tracker"]
        tracker.record_risk_rejected.assert_called_once()

    @pytest.mark.asyncio
    async def test_risk_reject_does_not_call_capital_manager(self):
        decision = RiskDecision.reject("max_positions", "Too many")
        pipeline = _build_pipeline(risk_decision=decision)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            await pipeline.execute(intent, market)

        pipeline._test_mocks["capital_manager"].calculate_size.assert_not_called()

    @pytest.mark.asyncio
    async def test_risk_halt_returns_system_halted(self):
        decision = RiskDecision.halt("max_drawdown", "Drawdown exceeded 10%")
        pipeline = _build_pipeline(risk_decision=decision)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            result = await pipeline.execute(intent, market)

        assert result.action == "SYSTEM_HALTED"
        assert "Drawdown" in result.reason

    @pytest.mark.asyncio
    async def test_risk_halt_appends_system_event(self):
        decision = RiskDecision.halt("max_drawdown", "Drawdown exceeded")
        pipeline = _build_pipeline(risk_decision=decision)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            await pipeline.execute(intent, market)

        event_repo = pipeline._test_mocks["event_repo"]
        event_repo.append.assert_called_once()


class TestCapitalManager:
    """Test capital manager sizing (step 4)."""

    @pytest.mark.asyncio
    async def test_sizing_none_returns_rejected(self):
        pipeline = _build_pipeline(sizing=None)
        # Override calculate_size to return None explicitly
        pipeline._capital.calculate_size = MagicMock(return_value=None)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            result = await pipeline.execute(intent, market)

        assert result.action == "REJECTED"
        assert "too small" in result.reason.lower() or "impossible" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_sizing_none_does_not_call_guard(self):
        pipeline = _build_pipeline(sizing=None)
        pipeline._capital.calculate_size = MagicMock(return_value=None)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            await pipeline.execute(intent, market)

        pipeline._test_mocks["execution_guard"].validate.assert_not_called()


class TestInsufficientBalance:
    """Test balance verification (step 5)."""

    @pytest.mark.asyncio
    async def test_insufficient_balance_returns_rejected(self):
        # Sizing produces quantity=0.01 * entry=42000 = 420 required
        # Portfolio has only 100 available
        portfolio = _portfolio_mock(available=Decimal("100"))
        pipeline = _build_pipeline(portfolio=portfolio)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            result = await pipeline.execute(intent, market)

        assert result.action == "REJECTED"
        assert "insufficient balance" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_insufficient_balance_does_not_call_guard(self):
        portfolio = _portfolio_mock(available=Decimal("100"))
        pipeline = _build_pipeline(portfolio=portfolio)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            await pipeline.execute(intent, market)

        pipeline._test_mocks["execution_guard"].validate.assert_not_called()


class TestExecutionGuard:
    """Test execution guard validation (step 6)."""

    @pytest.mark.asyncio
    async def test_guard_rejected_returns_guard_rejected(self):
        guard_result = GuardResult.reject("Spread too wide: 1.5%")
        pipeline = _build_pipeline(guard_result=guard_result)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            result = await pipeline.execute(intent, market)

        assert result.action == "GUARD_REJECTED"
        assert "Spread" in result.reason

    @pytest.mark.asyncio
    async def test_guard_rejected_records_event(self):
        guard_result = GuardResult.reject("Low volume")
        pipeline = _build_pipeline(guard_result=guard_result)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            await pipeline.execute(intent, market)

        tracker = pipeline._test_mocks["tracker"]
        tracker.record_guard_rejected.assert_called_once()

    @pytest.mark.asyncio
    async def test_guard_rejected_does_not_submit(self):
        guard_result = GuardResult.reject("Price drift")
        pipeline = _build_pipeline(guard_result=guard_result)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            await pipeline.execute(intent, market)

        pipeline._test_mocks["executor"].submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_guard_adjusted_quantity_used(self):
        adjusted = GuardResult(
            approved=True, reason="", adjusted_quantity=Decimal("0.005")
        )
        pipeline = _build_pipeline(guard_result=adjusted)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            await pipeline.execute(intent, market)

        executor = pipeline._test_mocks["executor"]
        call_kwargs = executor.submit.call_args
        assert call_kwargs.kwargs["quantity"] == Decimal("0.005")


class TestManualApproval:
    """Test manual approval flow (step 7b)."""

    @pytest.mark.asyncio
    async def test_manual_approval_returns_pending(self):
        pipeline = _build_pipeline()
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = True

            result = await pipeline.execute(intent, market)

        assert result.action == "PENDING_APPROVAL"
        assert "manual approval" in result.reason.lower() or "waiting" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_manual_approval_does_not_submit(self):
        pipeline = _build_pipeline()
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = True

            await pipeline.execute(intent, market)

        pipeline._test_mocks["executor"].submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_manual_approval_returns_details(self):
        pipeline = _build_pipeline()
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = True

            result = await pipeline.execute(intent, market)

        assert "quantity" in result.details
        assert "entry_price" in result.details
        assert "correlation_id" in result.details

    @pytest.mark.asyncio
    async def test_manual_approval_notification_failure_does_not_break(self):
        pipeline = _build_pipeline()
        intent = _intent()
        market = _market()

        with (
            patch("app.pipeline.orchestrator.settings") as mock_settings,
            patch(
                "app.core.notifications.notifier.notify_pending_approval",
                side_effect=Exception("Telegram down"),
            ),
        ):
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = True

            result = await pipeline.execute(intent, market)

        # Should still return PENDING_APPROVAL despite notification failure
        assert result.action == "PENDING_APPROVAL"


class TestPartialFill:
    """Test partial fill handling (step 9)."""

    @pytest.mark.asyncio
    async def test_partial_fill_returns_executed(self):
        partial_fill = _fill(quantity=Decimal("0.005"))  # Less than 0.01 requested
        pipeline = _build_pipeline(fill=partial_fill)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            result = await pipeline.execute(intent, market)

        assert result.action == "EXECUTED"

    @pytest.mark.asyncio
    async def test_partial_fill_position_uses_actual_quantity(self):
        partial_fill = _fill(quantity=Decimal("0.005"))
        pipeline = _build_pipeline(fill=partial_fill)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            await pipeline.execute(intent, market)

        pos_mgr = pipeline._test_mocks["position_mgr"]
        call_kwargs = pos_mgr.open_position.call_args
        # The fill passed to open_position should have the actual quantity
        assert call_kwargs.kwargs["fill"].quantity == Decimal("0.005")


class TestPortfolioNotFound:
    """Test when portfolio doesn't exist (step 2)."""

    @pytest.mark.asyncio
    async def test_no_portfolio_returns_error(self):
        pipeline = _build_pipeline()
        # Override the session.execute to return None for portfolio
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        pipeline._session.execute = AsyncMock(return_value=mock_result)

        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            result = await pipeline.execute(intent, market)

        assert result.action == "ERROR"
        assert "portfolio" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_no_portfolio_does_not_call_risk_manager(self):
        pipeline = _build_pipeline()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        pipeline._session.execute = AsyncMock(return_value=mock_result)

        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            await pipeline.execute(intent, market)

        pipeline._test_mocks["risk_manager"].validate.assert_not_called()


class TestExceptionHandling:
    """Test generic exception handling (outer try/except)."""

    @pytest.mark.asyncio
    async def test_executor_exception_returns_error(self):
        pipeline = _build_pipeline()
        pipeline._executor.submit = AsyncMock(
            side_effect=Exception("Exchange connection timeout")
        )
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            result = await pipeline.execute(intent, market)

        assert result.action == "ERROR"
        assert "timeout" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_risk_manager_exception_returns_error(self):
        pipeline = _build_pipeline()
        pipeline._risk.validate = AsyncMock(
            side_effect=RuntimeError("DB connection lost")
        )
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            result = await pipeline.execute(intent, market)

        assert result.action == "ERROR"
        assert "DB connection" in result.reason


class TestMarketHours:
    """Test stock market hours validation (step 0b)."""

    @pytest.mark.asyncio
    async def test_stock_outside_market_hours_rejected(self):
        pipeline = _build_pipeline()
        intent = _intent(symbol="AAPL")
        market = _market(symbol="AAPL")

        with (
            patch("app.pipeline.orchestrator.settings") as mock_settings,
            patch(
                "app.pipeline.orchestrator.is_us_market_open", return_value=False
            ),
        ):
            mock_settings.stock_symbols = ["AAPL", "MSFT", "GOOGL"]

            result = await pipeline.execute(intent, market)

        assert result.action == "REJECTED"
        assert "market" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_stock_during_market_hours_proceeds(self):
        pipeline = _build_pipeline()
        intent = _intent(symbol="AAPL")
        market = _market(symbol="AAPL")

        with (
            patch("app.pipeline.orchestrator.settings") as mock_settings,
            patch(
                "app.pipeline.orchestrator.is_us_market_open", return_value=True
            ),
        ):
            mock_settings.stock_symbols = ["AAPL", "MSFT", "GOOGL"]
            mock_settings.require_manual_approval = False

            result = await pipeline.execute(intent, market)

        # Should not be rejected for market hours
        assert result.action != "REJECTED" or "market" not in result.reason.lower()

    @pytest.mark.asyncio
    async def test_crypto_ignores_market_hours(self):
        pipeline = _build_pipeline()
        intent = _intent(symbol="BTCUSDT")
        market = _market(symbol="BTCUSDT")

        with (
            patch("app.pipeline.orchestrator.settings") as mock_settings,
            patch(
                "app.pipeline.orchestrator.is_us_market_open", return_value=False
            ),
        ):
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            result = await pipeline.execute(intent, market)

        # Crypto should NOT be rejected for market hours
        assert result.action != "REJECTED" or "market" not in result.reason.lower()

    @pytest.mark.asyncio
    async def test_market_hours_checked_before_system_status(self):
        """Stock market hours rejection should happen before system status check."""
        pipeline = _build_pipeline(system_status="HALTED")
        intent = _intent(symbol="AAPL")
        market = _market(symbol="AAPL")

        with (
            patch("app.pipeline.orchestrator.settings") as mock_settings,
            patch(
                "app.pipeline.orchestrator.is_us_market_open", return_value=False
            ),
        ):
            mock_settings.stock_symbols = ["AAPL", "MSFT"]

            result = await pipeline.execute(intent, market)

        # Should be REJECTED for market hours, not SYSTEM_HALTED
        assert result.action == "REJECTED"
        assert "market" in result.reason.lower()


# ── REDUCE_SIZE Tests ──


class TestReduceSize:
    """Test REDUCE_SIZE risk decision (step 4b)."""

    @pytest.mark.asyncio
    async def test_reduce_size_caps_quantity(self):
        decision = RiskDecision(
            action=RiskAction.REDUCE_SIZE,
            rule="max_exposure",
            reason="Exposure too high",
            details={"max_qty": "0.005"},
        )
        pipeline = _build_pipeline(risk_decision=decision)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            result = await pipeline.execute(intent, market)

        assert result.action == "EXECUTED"
        # The executor should have been called with the reduced quantity
        executor = pipeline._test_mocks["executor"]
        call_kwargs = executor.submit.call_args
        assert call_kwargs.kwargs["quantity"] == Decimal("0.005")

    @pytest.mark.asyncio
    async def test_reduce_size_no_effect_when_already_smaller(self):
        """If sizing quantity is already below max_qty, no reduction happens."""
        decision = RiskDecision(
            action=RiskAction.REDUCE_SIZE,
            rule="max_exposure",
            reason="Exposure check",
            details={"max_qty": "1.0"},  # Much larger than default 0.01
        )
        pipeline = _build_pipeline(risk_decision=decision)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            result = await pipeline.execute(intent, market)

        assert result.action == "EXECUTED"
        executor = pipeline._test_mocks["executor"]
        call_kwargs = executor.submit.call_args
        # Should use original sizing quantity (0.01), not the larger max_qty
        assert call_kwargs.kwargs["quantity"] == Decimal("0.01")

    @pytest.mark.asyncio
    async def test_reduce_size_without_max_qty_proceeds(self):
        """If REDUCE_SIZE but no max_qty in details, proceed with original sizing."""
        decision = RiskDecision(
            action=RiskAction.REDUCE_SIZE,
            rule="max_exposure",
            reason="Exposure check",
            details={},
        )
        pipeline = _build_pipeline(risk_decision=decision)
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            result = await pipeline.execute(intent, market)

        assert result.action == "EXECUTED"


# ── execute_approved_order Tests ──


class TestSubmitRetry:
    """Test retry behavior on exchange submission."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        """If first submit fails and second succeeds, pipeline should return EXECUTED."""
        pipeline = _build_pipeline()
        good_fill = _fill()
        pipeline._executor.submit = AsyncMock(
            side_effect=[ConnectionError("timeout"), good_fill]
        )
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            result = await pipeline.execute(intent, market)

        assert result.action == "EXECUTED"
        assert pipeline._executor.submit.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted_returns_error(self):
        """If all retries fail, pipeline should return ERROR."""
        pipeline = _build_pipeline()
        pipeline._executor.submit = AsyncMock(
            side_effect=ConnectionError("exchange unreachable")
        )
        intent = _intent()
        market = _market()

        with patch("app.pipeline.orchestrator.settings") as mock_settings:
            mock_settings.stock_symbols = ["AAPL", "MSFT"]
            mock_settings.require_manual_approval = False

            result = await pipeline.execute(intent, market)

        assert result.action == "ERROR"
        assert "exchange unreachable" in result.reason
        # max_retries=2 means 3 total attempts
        assert pipeline._executor.submit.call_count == 3


class TestExecuteApprovedOrder:
    """Test the shared execution path used by ApprovalExecutor."""

    def _make_order(self, **overrides):
        order = MagicMock()
        order.id = uuid4()
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
        order.filled_qty = None
        order.avg_fill_price = None
        order.exchange_order_id = None
        return order

    @pytest.mark.asyncio
    async def test_approved_order_executed(self):
        pipeline = _build_pipeline()
        order = self._make_order()
        market = _market()

        result = await pipeline.execute_approved_order(order, market)

        assert result.action == "EXECUTED"

    @pytest.mark.asyncio
    async def test_approved_order_no_portfolio(self):
        pipeline = _build_pipeline()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        pipeline._session.execute = AsyncMock(return_value=mock_result)

        order = self._make_order()
        market = _market()

        result = await pipeline.execute_approved_order(order, market)

        assert result.action == "ERROR"
        assert order.status == OrderStatus.REJECTED.value

    @pytest.mark.asyncio
    async def test_approved_order_insufficient_balance(self):
        portfolio = _portfolio_mock(available=Decimal("100"))
        pipeline = _build_pipeline(portfolio=portfolio)
        order = self._make_order()
        market = _market()

        result = await pipeline.execute_approved_order(order, market)

        assert result.action == "REJECTED"
        assert order.status == OrderStatus.REJECTED.value

    @pytest.mark.asyncio
    async def test_approved_order_guard_rejected(self):
        guard_result = GuardResult.reject("Spread too wide")
        pipeline = _build_pipeline(guard_result=guard_result)
        order = self._make_order()
        market = _market()

        result = await pipeline.execute_approved_order(order, market)

        assert result.action == "GUARD_REJECTED"
        assert order.status == OrderStatus.REJECTED.value

    @pytest.mark.asyncio
    async def test_approved_order_exception_rejects(self):
        pipeline = _build_pipeline()
        pipeline._executor.submit = AsyncMock(
            side_effect=Exception("Exchange down")
        )
        order = self._make_order()
        market = _market()

        result = await pipeline.execute_approved_order(order, market)

        assert result.action == "ERROR"
        assert order.status == OrderStatus.REJECTED.value
