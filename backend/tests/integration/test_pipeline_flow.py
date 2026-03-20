"""Integration tests: full pipeline flow against real DB.

Tests the complete signal → risk → capital → guard → execute → position → trade cycle.
Verifies balance consistency at every step.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.enums import (
    ExecutionMode,
    OrderSide,
    OrderStatus,
    PositionStatus,
    RiskAction,
    SignalType,
)
from app.models.portfolio import Portfolio
from app.pipeline.capital_manager.capital_manager import CapitalManager
from app.pipeline.execution.base import Fill
from app.pipeline.execution.guard import ExecutionGuard, MarketSnapshot
from app.pipeline.execution.paper_engine import PaperEngine
from app.pipeline.orchestrator import TradingPipeline, _validate_sl_tp
from app.pipeline.position_manager.position_manager import PositionManager
from app.pipeline.risk_manager.risk_manager import RiskManager
from app.pipeline.risk_manager.rules.base import RiskDecision
from app.pipeline.strategy.base import TradeIntent
from app.repositories.position_repo import PositionRepository
from app.services.portfolio_service import PortfolioService


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


def _market() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTCUSDT",
        price=Decimal("42000"),
        bid=Decimal("41990"),
        ask=Decimal("42010"),
        volume_24h=Decimal("500000"),
    )


async def _create_portfolio(session, balance: Decimal = Decimal("10000")) -> Portfolio:
    """Create a test portfolio and commit so FOR UPDATE queries can see it."""
    svc = PortfolioService(session)
    portfolio = await svc.get_or_create(ExecutionMode.PAPER, balance)
    await session.commit()
    return portfolio


async def _create_order_for_fill(session, symbol: str, price: Decimal, qty: Decimal):
    """Create signal + order so position FK is satisfied. Returns order_id."""
    from app.models.signal import Signal as SignalModel
    from app.models.order import Order

    signal = SignalModel(
        symbol=symbol, signal_type="BUY", confidence=Decimal("0.7"), timeframe="1h",
        indicators={}, entry_price=price, stop_loss=price * Decimal("0.98"),
        take_profit=price * Decimal("1.04"), strategy_id=uuid4(),
        expires_at=datetime.now(timezone.utc),
    )
    session.add(signal)
    await session.flush()

    order = Order(
        signal_id=signal.id, symbol=symbol, side="BUY", order_type="MARKET",
        status="FILLED", requested_qty=qty, filled_qty=qty,
        requested_price=price, avg_fill_price=price, stop_loss=price * Decimal("0.98"),
        take_profit=price * Decimal("1.04"), execution_mode="PAPER",
        risk_decision={}, capital_decision={},
    )
    session.add(order)
    await session.flush()
    return order.id


def _mock_executor() -> PaperEngine:
    """Create a paper engine with mocked Redis."""
    engine = PaperEngine(slippage_pct=Decimal("0.0005"), simulate_latency=False)
    mock_redis = AsyncMock()
    mock_redis.hgetall = AsyncMock(return_value={})
    engine._redis = mock_redis
    return engine


def _mock_risk_manager(approve: bool = True) -> RiskManager:
    """Create a risk manager that always approves or rejects."""
    rm = RiskManager(rules=[], circuit_breaker=AsyncMock())
    rm._circuit_breaker.is_active = AsyncMock(return_value=False)
    if not approve:
        from app.pipeline.risk_manager.rules.base import RiskRule, RiskContext
        class RejectRule(RiskRule):
            @property
            def name(self): return "test_reject"
            async def evaluate(self, ctx): return RiskDecision.reject("test", "rejected")
        rm._rules = [RejectRule()]
    return rm


# ── PIPELINE EXECUTION TESTS ──


class TestPipelineExecution:
    """Test full pipeline with real DB session."""

    @pytest.mark.asyncio
    async def test_full_pipeline_creates_position_and_updates_balance(self, session):
        """CRITICAL: Complete signal → position + portfolio balance correct."""
        portfolio = await _create_portfolio(session)
        initial_balance = portfolio.total_balance

        # Mock Redis for system status
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="RUNNING")

        pipeline = TradingPipeline(
            risk_manager=_mock_risk_manager(approve=True),
            capital_manager=CapitalManager(risk_per_trade_pct=Decimal("0.01"), max_exposure_per_symbol_pct=Decimal("0.5")),
            execution_guard=ExecutionGuard(),
            executor=_mock_executor(),
            session=session,
        )
        pipeline._redis = mock_redis

        result = await pipeline.execute(_intent(), _market())

        assert result.action == "EXECUTED", f"Expected EXECUTED, got {result.action}: {result.reason}"
        assert result.order_id is not None
        assert result.position_id is not None

        # Verify portfolio balance invariant
        await session.refresh(portfolio)
        assert portfolio.available_balance + portfolio.allocated_balance == portfolio.total_balance, \
            f"Balance invariant broken: available={portfolio.available_balance} + allocated={portfolio.allocated_balance} != total={portfolio.total_balance}"

        # Verify balance decreased
        assert portfolio.available_balance < initial_balance
        assert portfolio.allocated_balance > 0

    @pytest.mark.asyncio
    async def test_risk_rejection_does_not_change_balance(self, session):
        """Risk rejection must NOT modify portfolio."""
        portfolio = await _create_portfolio(session)
        initial_available = portfolio.available_balance

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="RUNNING")

        pipeline = TradingPipeline(
            risk_manager=_mock_risk_manager(approve=False),
            capital_manager=CapitalManager(),
            execution_guard=ExecutionGuard(),
            executor=_mock_executor(),
            session=session,
        )
        pipeline._redis = mock_redis

        result = await pipeline.execute(_intent(), _market())

        assert result.action == "REJECTED"

        await session.refresh(portfolio)
        assert portfolio.available_balance == initial_available
        assert portfolio.allocated_balance == Decimal("0")

    @pytest.mark.asyncio
    async def test_invalid_sl_tp_rejected_without_db_changes(self, session):
        """Invalid SL/TP must reject immediately, no DB writes."""
        portfolio = await _create_portfolio(session)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="RUNNING")

        pipeline = TradingPipeline(
            risk_manager=_mock_risk_manager(),
            capital_manager=CapitalManager(),
            execution_guard=ExecutionGuard(),
            executor=_mock_executor(),
            session=session,
        )
        pipeline._redis = mock_redis

        bad_intent = _intent(stop_loss=Decimal("45000"))  # SL above entry for BUY

        result = await pipeline.execute(bad_intent, _market())

        assert result.action == "REJECTED"
        assert "SL/TP" in result.reason

        await session.refresh(portfolio)
        assert portfolio.available_balance == Decimal("10000")

    @pytest.mark.asyncio
    async def test_system_halted_no_execution(self, session):
        """HALTED system must reject without touching DB."""
        await _create_portfolio(session)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="HALTED")

        pipeline = TradingPipeline(
            risk_manager=_mock_risk_manager(),
            capital_manager=CapitalManager(),
            execution_guard=ExecutionGuard(),
            executor=_mock_executor(),
            session=session,
        )
        pipeline._redis = mock_redis

        result = await pipeline.execute(_intent(), _market())
        assert result.action == "SYSTEM_HALTED"


# ── BALANCE CONSISTENCY TESTS ──


class TestBalanceConsistency:
    """Verify available + allocated == total at all times."""

    @pytest.mark.asyncio
    async def test_balance_after_open_and_close(self, session):
        """Open position → close with profit → balance correct."""
        portfolio = await _create_portfolio(session, Decimal("10000"))
        pos_mgr = PositionManager(session)
        portfolio_svc = PortfolioService(session)

        order_id = await _create_order_for_fill(session, "BTCUSDT", Decimal("42000"), Decimal("0.01"))

        fill = Fill(
            order_id=order_id,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("42000"),
            quantity=Decimal("0.01"),
            timestamp=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.PAPER,
        )

        # Open position
        position = await pos_mgr.open_position(
            fill=fill,
            stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
            strategy_id=uuid4(),
            signal_confidence=Decimal("0.75"),
        )

        # Simulate portfolio update (as orchestrator does)
        fill_value = fill.price * fill.quantity  # 420
        portfolio.available_balance -= fill_value
        portfolio.allocated_balance += fill_value
        await session.flush()

        # Verify invariant after open
        await session.refresh(portfolio)
        assert portfolio.available_balance + portfolio.allocated_balance == portfolio.total_balance

        # Close position with profit
        trade = await pos_mgr.close_position(
            position_id=position.id,
            exit_price=Decimal("43000"),
            reason="TAKE_PROFIT",
        )

        assert trade.pnl > 0  # Profitable

        # Update portfolio
        await portfolio_svc.record_close(ExecutionMode.PAPER, fill_value, trade.pnl)

        # Verify invariant after close
        await session.refresh(portfolio)
        assert portfolio.available_balance + portfolio.allocated_balance == portfolio.total_balance
        assert portfolio.total_balance > Decimal("10000")  # Profit added

    @pytest.mark.asyncio
    async def test_balance_after_multiple_positions(self, session):
        """Open 3 positions, close all, balance must equal initial + total PnL."""
        initial = Decimal("10000")
        portfolio = await _create_portfolio(session, initial)
        pos_mgr = PositionManager(session)
        portfolio_svc = PortfolioService(session)

        positions = []
        fill_values = []

        # Open 3 positions
        for i, (price, qty) in enumerate([
            (Decimal("42000"), Decimal("0.01")),
            (Decimal("3400"), Decimal("0.1")),
            (Decimal("180"), Decimal("1.0")),
        ]):
            oid = await _create_order_for_fill(session, f"SYM{i}USDT", price, qty)
            fill = Fill(
                order_id=oid, symbol=f"SYM{i}USDT", side=OrderSide.BUY,
                price=price, quantity=qty,
                timestamp=datetime.now(timezone.utc),
                execution_mode=ExecutionMode.PAPER,
            )
            pos = await pos_mgr.open_position(
                fill=fill, stop_loss=price * Decimal("0.98"),
                take_profit=price * Decimal("1.04"),
                strategy_id=uuid4(), signal_confidence=Decimal("0.7"),
            )
            fv = price * qty
            portfolio.available_balance -= fv
            portfolio.allocated_balance += fv
            positions.append(pos)
            fill_values.append(fv)

        await session.flush()
        await session.refresh(portfolio)
        assert portfolio.available_balance + portfolio.allocated_balance == initial

        # Close all: win, loss, win
        exit_prices = [Decimal("43000"), Decimal("3300"), Decimal("190")]
        total_pnl = Decimal("0")

        for pos, fv, exit_p in zip(positions, fill_values, exit_prices):
            trade = await pos_mgr.close_position(
                position_id=pos.id, exit_price=exit_p, reason="MANUAL_CLOSE",
            )
            await portfolio_svc.record_close(ExecutionMode.PAPER, fv, trade.pnl)
            total_pnl += trade.pnl

        await session.refresh(portfolio)
        assert portfolio.allocated_balance == Decimal("0")
        expected_total = initial + total_pnl
        assert abs(portfolio.total_balance - expected_total) < Decimal("0.01"), \
            f"total={portfolio.total_balance} expected={expected_total}"
        assert portfolio.available_balance + portfolio.allocated_balance == portfolio.total_balance


# ── POSITION MANAGER DB TESTS ──


class TestPositionManagerDB:
    @pytest.mark.asyncio
    async def test_open_position_persists(self, session):
        """Position is actually saved in DB."""
        await _create_portfolio(session)
        pos_mgr = PositionManager(session)

        oid = await _create_order_for_fill(session, "BTCUSDT", Decimal("42000"), Decimal("0.01"))
        fill = Fill(
            order_id=oid, symbol="BTCUSDT", side=OrderSide.BUY,
            price=Decimal("42000"), quantity=Decimal("0.01"),
            timestamp=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.PAPER,
        )
        pos = await pos_mgr.open_position(
            fill=fill, stop_loss=Decimal("41000"), take_profit=Decimal("44000"),
            strategy_id=uuid4(), signal_confidence=Decimal("0.8"),
        )

        assert pos.id is not None
        assert pos.status == PositionStatus.OPEN.value
        assert pos.strategy_id is not None

        # Verify in DB
        repo = PositionRepository(session)
        loaded = await repo.get_by_id(pos.id)
        assert loaded is not None
        assert loaded.symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_close_position_creates_trade(self, session):
        """Closing position creates a Trade record."""
        await _create_portfolio(session)
        pos_mgr = PositionManager(session)

        oid = await _create_order_for_fill(session, "ETHUSDT", Decimal("3400"), Decimal("0.1"))
        fill = Fill(
            order_id=oid, symbol="ETHUSDT", side=OrderSide.BUY,
            price=Decimal("3400"), quantity=Decimal("0.1"),
            timestamp=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.PAPER,
        )
        pos = await pos_mgr.open_position(
            fill=fill, stop_loss=Decimal("3300"), take_profit=Decimal("3600"),
            strategy_id=uuid4(), signal_confidence=Decimal("0.7"),
        )

        trade = await pos_mgr.close_position(
            position_id=pos.id, exit_price=Decimal("3500"), reason="TAKE_PROFIT",
        )

        assert trade is not None
        assert trade.pnl == (Decimal("3500") - Decimal("3400")) * Decimal("0.1")
        assert trade.pnl > 0

        # Position is now closed
        await session.refresh(pos)
        assert pos.status == PositionStatus.CLOSED.value

    @pytest.mark.asyncio
    async def test_close_already_closed_fails(self, session):
        """Cannot close an already closed position."""
        await _create_portfolio(session)
        pos_mgr = PositionManager(session)

        oid = await _create_order_for_fill(session, "SOLUSDT", Decimal("180"), Decimal("1.0"))
        fill = Fill(
            order_id=oid, symbol="SOLUSDT", side=OrderSide.BUY,
            price=Decimal("180"), quantity=Decimal("1.0"),
            timestamp=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.PAPER,
        )
        pos = await pos_mgr.open_position(
            fill=fill, stop_loss=Decimal("175"), take_profit=Decimal("190"),
            strategy_id=uuid4(), signal_confidence=Decimal("0.6"),
        )

        # Close once
        await pos_mgr.close_position(pos.id, Decimal("185"), "TAKE_PROFIT")

        # Try to close again
        from app.core.exceptions import InvalidStateTransitionError
        with pytest.raises(InvalidStateTransitionError):
            await pos_mgr.close_position(pos.id, Decimal("186"), "MANUAL")
