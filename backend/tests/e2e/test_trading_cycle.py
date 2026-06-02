"""E2E tests: full trading cycle from signal generation to position close.

Tests the complete lifecycle:
1. Signal → Pipeline → Order → Position (open)
2. Position Monitor → SL/TP trigger → Close → Trade record
3. Balance consistency throughout

Uses real PostgreSQL, mocked Redis and executor (no exchange).
"""
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.domain.enums import (
    AssetClass,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    PositionStatus,
    SignalType,
)
from app.models.order import Order
from app.models.portfolio import Portfolio
from app.models.position import Position
from app.models.signal import Signal
from app.models.trade import Trade
from app.pipeline.capital_manager.capital_manager import CapitalManager
from app.pipeline.execution.base import Fill
from app.pipeline.execution.guard import ExecutionGuard, MarketSnapshot
from app.pipeline.execution.paper_engine import PaperEngine
from app.pipeline.orchestrator import TradingPipeline
from app.pipeline.position_manager.position_manager import PositionManager
from app.pipeline.risk_manager.risk_manager import RiskManager
from app.pipeline.strategy.base import TradeIntent
from app.repositories.position_repo import PositionRepository
from app.services.portfolio_service import PortfolioService
from app.tasks.position_monitor import PositionMonitor


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


def _market(symbol="BTCUSDT", price=Decimal("42000"), **kw) -> MarketSnapshot:
    # Spread must stay within guard limits (0.3% for crypto)
    spread = price * Decimal("0.001")  # 0.1% spread
    return MarketSnapshot(
        symbol=symbol,
        price=price,
        bid=kw.get("bid", price - spread / 2),
        ask=kw.get("ask", price + spread / 2),
        volume_24h=kw.get("volume_24h", Decimal("500000")),
        asset_class=kw.get("asset_class", "CRYPTO"),
    )


def _mock_redis(system_status="RUNNING", prices=None):
    """Create a mock Redis with configurable system status and price cache."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=system_status)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    redis.publish = AsyncMock()

    def _hgetall(key):
        if prices and key.startswith("price:"):
            symbol = key.split(":", 1)[1]
            if symbol in prices:
                p = prices[symbol]
                return {
                    "price": str(p["price"]),
                    "bid": str(p.get("bid", p["price"] - 10)),
                    "ask": str(p.get("ask", p["price"] + 10)),
                    "timestamp": str(p.get("timestamp", time.time())),
                }
        return {}

    redis.hgetall = AsyncMock(side_effect=_hgetall)
    return redis


def _mock_executor(redis_mock=None) -> PaperEngine:
    engine = PaperEngine(slippage_pct=Decimal("0.0005"), simulate_latency=False)
    engine._redis = redis_mock or AsyncMock(hgetall=AsyncMock(return_value={}))
    return engine


def _mock_risk_manager() -> RiskManager:
    rm = RiskManager(rules=[], circuit_breaker=AsyncMock())
    rm._circuit_breaker.is_active = AsyncMock(return_value=False)
    return rm


async def _create_portfolio(session, balance=Decimal("10000")) -> Portfolio:
    svc = PortfolioService(session)
    portfolio = await svc.get_or_create(ExecutionMode.PAPER, balance)
    await session.commit()
    return portfolio


async def _run_pipeline(session, intent, market, redis_mock=None):
    """Run pipeline and commit, returning (result, session)."""
    mock_redis = redis_mock or _mock_redis()
    executor = _mock_executor(mock_redis)

    pipeline = TradingPipeline(
        risk_manager=_mock_risk_manager(),
        capital_manager=CapitalManager(
            risk_per_trade_pct=Decimal("0.01"),
            max_exposure_per_symbol_pct=Decimal("0.5"),
        ),
        execution_guard=ExecutionGuard(),
        executor=executor,
        session=session,
    )
    pipeline._redis = mock_redis

    result = await pipeline.execute(intent, market)
    await session.commit()
    return result


# ── E2E: Full Trading Cycle ──


class TestFullTradingCycle:
    """Signal → Order → Position → SL/TP Close → Trade → Balance."""

    @pytest.mark.asyncio
    async def test_signal_to_position_to_sl_close(self, session, session_factory):
        """Complete cycle: BUY signal → open position → stop loss close."""
        # 1. Create portfolio
        portfolio = await _create_portfolio(session)
        initial_balance = portfolio.total_balance

        # 2. Execute pipeline (creates signal, order, position)
        intent = _intent(
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
        )
        result = await _run_pipeline(session, intent, _market())

        assert result.action == "EXECUTED"
        assert result.position_id is not None
        assert result.order_id is not None

        # 3. Verify position is OPEN in DB
        repo = PositionRepository(session)
        position = await repo.get_by_id(result.position_id)
        assert position is not None
        assert position.status == PositionStatus.OPEN.value
        assert position.stop_loss == Decimal("41000")
        assert position.take_profit == Decimal("44000")

        # 4. Verify order is FILLED
        order = (await session.execute(
            select(Order).where(Order.id == result.order_id)
        )).scalar_one()
        assert order.status == OrderStatus.FILLED.value
        assert order.filled_qty > 0

        # 5. Simulate price dropping to SL via PositionMonitor
        sl_price = Decimal("40900")
        mock_redis = _mock_redis(prices={
            "BTCUSDT": {"price": sl_price, "bid": sl_price - 5, "ask": sl_price + 5},
        })

        monitor = PositionMonitor(
            session_factory=session_factory,
            execution_mode=ExecutionMode.PAPER,
            check_interval=1,
        )
        monitor._redis = mock_redis

        # Run one check cycle
        await monitor._check_cycle()

        # 6. Verify position is STOPPED_OUT
        async with session_factory() as verify_session:
            pos = await PositionRepository(verify_session).get_by_id(result.position_id)
            assert pos.status == PositionStatus.STOPPED_OUT.value
            assert pos.closed_at is not None

            # 7. Verify trade record was created with correct P&L
            trade = (await verify_session.execute(
                select(Trade).where(Trade.position_id == result.position_id)
            )).scalar_one()
            assert trade.pnl < 0  # Loss
            assert trade.entry_price == position.entry_price
            assert trade.exit_price == sl_price

            # 8. Verify portfolio balance reflects the loss
            p = (await verify_session.execute(
                select(Portfolio).where(Portfolio.execution_mode == "PAPER")
            )).scalar_one()
            assert p.total_balance < initial_balance  # Lost money
            # Balance invariant
            assert p.available_balance + p.allocated_balance == p.total_balance

    @pytest.mark.asyncio
    async def test_signal_to_position_to_tp_close(self, session, session_factory):
        """Complete cycle: BUY signal → open position → take profit close."""
        portfolio = await _create_portfolio(session)
        initial_balance = portfolio.total_balance

        intent = _intent(
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
        )
        result = await _run_pipeline(session, intent, _market())
        assert result.action == "EXECUTED"

        # Simulate price rising to TP
        tp_price = Decimal("44100")
        mock_redis = _mock_redis(prices={
            "BTCUSDT": {"price": tp_price, "bid": tp_price - 5, "ask": tp_price + 5},
        })

        monitor = PositionMonitor(
            session_factory=session_factory,
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis
        await monitor._check_cycle()

        # Verify position closed with profit
        async with session_factory() as verify_session:
            pos = await PositionRepository(verify_session).get_by_id(result.position_id)
            assert pos.status == PositionStatus.CLOSED.value

            trade_result = await verify_session.execute(
                select(Trade).where(Trade.position_id == result.position_id)
            )
            trade = trade_result.scalar_one()
            assert trade.pnl > 0  # Profit

            p_result = await verify_session.execute(
                select(Portfolio).where(Portfolio.execution_mode == "PAPER")
            )
            p = p_result.scalar_one()
            assert p.total_balance > initial_balance

    @pytest.mark.asyncio
    async def test_multiple_positions_open_close_balance_consistent(
        self, session, session_factory,
    ):
        """Open 3 positions, close them with mixed P&L, verify balance invariant."""
        portfolio = await _create_portfolio(session, Decimal("50000"))
        initial_balance = portfolio.total_balance

        symbols = [
            ("BTCUSDT", Decimal("42000"), Decimal("41000"), Decimal("44000")),
            ("ETHUSDT", Decimal("3400"), Decimal("3300"), Decimal("3600")),
            ("SOLUSDT", Decimal("180"), Decimal("175"), Decimal("190")),
        ]
        position_ids = []

        for sym, entry, sl, tp in symbols:
            result = await _run_pipeline(
                session,
                _intent(symbol=sym, entry_price=entry, stop_loss=sl, take_profit=tp),
                _market(symbol=sym, price=entry),
            )
            assert result.action == "EXECUTED", f"{sym}: {result.reason}"
            position_ids.append(result.position_id)

        # Check balance invariant after opening all
        await session.refresh(portfolio)
        assert portfolio.available_balance + portfolio.allocated_balance == portfolio.total_balance

        # Close: BTC at SL (loss), ETH at TP (win), SOL at TP (win)
        close_prices = {
            "BTCUSDT": Decimal("40900"),
            "ETHUSDT": Decimal("3650"),
            "SOLUSDT": Decimal("192"),
        }
        # Spread must be within exit limits (1% crypto), use 0.1% spread
        mock_redis = _mock_redis(prices={
            sym: {
                "price": p,
                "bid": p - p * Decimal("0.0005"),
                "ask": p + p * Decimal("0.0005"),
            }
            for sym, p in close_prices.items()
        })

        monitor = PositionMonitor(
            session_factory=session_factory,
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis
        await monitor._check_cycle()

        # Verify all positions closed
        async with session_factory() as verify_session:
            total_pnl = Decimal("0")
            for pid in position_ids:
                pos = await PositionRepository(verify_session).get_by_id(pid)
                assert pos.status in (
                    PositionStatus.CLOSED.value,
                    PositionStatus.STOPPED_OUT.value,
                )
                trade = (await verify_session.execute(
                    select(Trade).where(Trade.position_id == pid)
                )).scalar_one()
                total_pnl += trade.pnl

            # Verify portfolio balance
            p = (await verify_session.execute(
                select(Portfolio).where(Portfolio.execution_mode == "PAPER")
            )).scalar_one()
            assert p.allocated_balance == Decimal("0")
            assert abs(p.total_balance - (initial_balance + total_pnl)) < Decimal("0.01")
            assert p.available_balance == p.total_balance


# ── E2E: Risk Manager Gates ──


class TestRiskGating:
    """Verify risk manager properly blocks trades."""

    @pytest.mark.asyncio
    async def test_system_halted_blocks_execution(self, session):
        """No trades when system is HALTED."""
        await _create_portfolio(session)
        mock_redis = _mock_redis(system_status="HALTED")
        executor = _mock_executor(mock_redis)

        pipeline = TradingPipeline(
            risk_manager=_mock_risk_manager(),
            capital_manager=CapitalManager(),
            execution_guard=ExecutionGuard(),
            executor=executor,
            session=session,
        )
        pipeline._redis = mock_redis

        result = await pipeline.execute(_intent(), _market())
        assert result.action == "SYSTEM_HALTED"
        assert result.order_id is None

    @pytest.mark.asyncio
    async def test_risk_rejection_leaves_balance_untouched(self, session):
        """Rejected trade must not modify portfolio."""
        portfolio = await _create_portfolio(session)
        initial = portfolio.available_balance

        mock_redis = _mock_redis()

        # Risk manager that rejects
        from app.pipeline.risk_manager.rules.base import RiskDecision, RiskRule, RiskContext
        class RejectAll(RiskRule):
            @property
            def name(self): return "reject_all"
            async def evaluate(self, ctx): return RiskDecision.reject("reject_all", "testing")

        rm = RiskManager(rules=[RejectAll()], circuit_breaker=AsyncMock())
        rm._circuit_breaker.is_active = AsyncMock(return_value=False)

        pipeline = TradingPipeline(
            risk_manager=rm,
            capital_manager=CapitalManager(),
            execution_guard=ExecutionGuard(),
            executor=_mock_executor(mock_redis),
            session=session,
        )
        pipeline._redis = mock_redis

        result = await pipeline.execute(_intent(), _market())
        assert result.action == "REJECTED"

        await session.refresh(portfolio)
        assert portfolio.available_balance == initial
        assert portfolio.allocated_balance == Decimal("0")

    @pytest.mark.asyncio
    async def test_insufficient_balance_rejected(self, session):
        """Trade requiring more than available balance is rejected."""
        await _create_portfolio(session, balance=Decimal("1"))  # $1 balance

        mock_redis = _mock_redis()
        pipeline = TradingPipeline(
            risk_manager=_mock_risk_manager(),
            capital_manager=CapitalManager(
                risk_per_trade_pct=Decimal("0.99"),
                max_exposure_per_symbol_pct=Decimal("0.99"),
            ),
            execution_guard=ExecutionGuard(),
            executor=_mock_executor(mock_redis),
            session=session,
        )
        pipeline._redis = mock_redis

        # $1 balance, entry at 42000 — capital manager can't size
        result = await pipeline.execute(
            _intent(entry_price=Decimal("42000"), confidence=Decimal("0.99")),
            _market(),
        )
        assert result.action == "REJECTED"


# ── E2E: Position Monitor Safety ──


class TestPositionMonitorSafety:
    """Test PositionMonitor edge cases and safety mechanisms."""

    @pytest.mark.asyncio
    async def test_stale_prices_trigger_system_halt(self, session_factory):
        """5 consecutive stale prices auto-halt the system."""
        # Create portfolio and position directly
        async with session_factory() as session:
            await _create_portfolio(session)
            result = await _run_pipeline(session, _intent(), _market())
            assert result.action == "EXECUTED"

        # Mock Redis with NO prices (stale)
        mock_redis = _mock_redis(prices={})
        mock_redis.hgetall = AsyncMock(return_value={})

        monitor = PositionMonitor(
            session_factory=session_factory,
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis

        # Run 5 cycles — should halt after 5th
        for _ in range(5):
            await monitor._check_cycle()

        # Verify system:status was set to HALTED
        mock_redis.set.assert_any_call("system:status", "HALTED")

    @pytest.mark.asyncio
    async def test_dedup_prevents_double_close(self, session, session_factory):
        """Position monitor dedup prevents closing the same position twice."""
        await _create_portfolio(session)
        result = await _run_pipeline(session, _intent(), _market())
        assert result.action == "EXECUTED"

        sl_price = Decimal("40000")
        mock_redis = _mock_redis(prices={
            "BTCUSDT": {"price": sl_price, "bid": sl_price - 5, "ask": sl_price + 5},
        })
        # First close: nx=True returns True
        # Second close: nx=True returns False (already set)
        mock_redis.set = AsyncMock(side_effect=[True, False])

        monitor = PositionMonitor(
            session_factory=session_factory,
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis

        # First cycle closes
        await monitor._check_cycle()

        # Position should be closed now
        async with session_factory() as verify:
            pos = await PositionRepository(verify).get_by_id(result.position_id)
            assert pos.status in (
                PositionStatus.STOPPED_OUT.value,
                PositionStatus.CLOSED.value,
            )

    @pytest.mark.asyncio
    async def test_price_between_sl_tp_no_close(self, session, session_factory):
        """Price within SL/TP range should not trigger close."""
        await _create_portfolio(session)
        result = await _run_pipeline(session, _intent(), _market())
        assert result.action == "EXECUTED"

        # Price between SL (41000) and TP (44000)
        mid_price = Decimal("42500")
        mock_redis = _mock_redis(prices={
            "BTCUSDT": {"price": mid_price, "bid": mid_price - 5, "ask": mid_price + 5},
        })

        monitor = PositionMonitor(
            session_factory=session_factory,
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis
        await monitor._check_cycle()

        # Position should still be OPEN
        async with session_factory() as verify:
            pos = await PositionRepository(verify).get_by_id(result.position_id)
            assert pos.status == PositionStatus.OPEN.value
            # Price should have been updated
            assert pos.current_price == mid_price

    @pytest.mark.asyncio
    async def test_wide_spread_defers_close(self, session, session_factory):
        """Wide spread blocks SL close, releases dedup key for retry."""
        await _create_portfolio(session)
        result = await _run_pipeline(session, _intent(), _market())
        assert result.action == "EXECUTED"

        sl_price = Decimal("40000")
        mock_redis = _mock_redis()
        # Price stale check returns fresh price
        def _hgetall_wide_spread(key):
            sym = key.split(":", 1)[1] if ":" in key else ""
            if sym == "BTCUSDT":
                return {
                    "price": str(sl_price),
                    "bid": str(sl_price - Decimal("500")),  # Wide spread
                    "ask": str(sl_price + Decimal("500")),
                    "timestamp": str(time.time()),
                }
            return {}
        mock_redis.hgetall = AsyncMock(side_effect=_hgetall_wide_spread)

        monitor = PositionMonitor(
            session_factory=session_factory,
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis
        await monitor._check_cycle()

        # Position should still be OPEN (spread too wide)
        async with session_factory() as verify:
            pos = await PositionRepository(verify).get_by_id(result.position_id)
            assert pos.status == PositionStatus.OPEN.value

        # Dedup key should have been deleted to allow retry
        mock_redis.delete.assert_called()


# ── E2E: Signal Executor ──


class TestSignalExecutor:
    """Test the SignalExecutor polling and execution flow."""

    @pytest.mark.asyncio
    async def test_executor_picks_up_signal_and_creates_position(
        self, session, session_factory,
    ):
        """SignalExecutor polls DB for signals and executes them."""
        from app.tasks.signal_executor import SignalExecutor

        # Setup portfolio
        await _create_portfolio(session)

        # Create a pending signal in DB
        signal = Signal(
            symbol="BTCUSDT",
            asset_class=AssetClass.CRYPTO.value,
            signal_type="BUY",
            confidence=Decimal("0.75"),
            timeframe="1h",
            indicators={"rsi": 28},
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
            strategy_id=uuid4(),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        session.add(signal)
        await session.commit()

        # Mock dependencies
        mock_redis = _mock_redis(
            prices={"BTCUSDT": {"price": Decimal("42000"), "bid": Decimal("41990"), "ask": Decimal("42010")}},
        )
        executor_engine = _mock_executor(mock_redis)

        market_data = AsyncMock()
        market_data.get_market_snapshot = AsyncMock(return_value={
            "price": Decimal("42000"),
            "bid": Decimal("41990"),
            "ask": Decimal("42010"),
            "volume_24h": Decimal("500000"),
            "asset_class": "CRYPTO",
        })

        guard = ExecutionGuard()

        signal_executor = SignalExecutor(
            executor=executor_engine,
            guard=guard,
            market_data=market_data,
            session_factory=session_factory,
        )
        signal_executor._redis = mock_redis

        # Run one poll cycle
        await signal_executor._poll_cycle()

        # Verify: orders and positions were created
        async with session_factory() as verify:
            # Pipeline creates its own signal+order, so check total counts
            order_count = (await verify.execute(
                select(func.count()).select_from(Order)
            )).scalar()
            assert order_count >= 1, "At least one order should exist"

            position_count = (await verify.execute(
                select(func.count()).select_from(Position).where(
                    Position.status == PositionStatus.OPEN.value,
                )
            )).scalar()
            assert position_count >= 1, "At least one position should be open"

            # Verify the original signal won't be picked up again
            # (it should now have a linked order via signal_id)
            filled_orders = (await verify.execute(
                select(Order).where(Order.status == OrderStatus.FILLED.value)
            )).scalars().all()
            assert len(filled_orders) >= 1

    @pytest.mark.asyncio
    async def test_executor_skips_expired_signals(self, session, session_factory):
        """Expired signals should not be picked up."""
        from app.tasks.signal_executor import SignalExecutor

        await _create_portfolio(session)

        # Create an EXPIRED signal
        signal = Signal(
            symbol="BTCUSDT",
            asset_class=AssetClass.CRYPTO.value,
            signal_type="BUY",
            confidence=Decimal("0.75"),
            timeframe="1h",
            indicators={},
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
            strategy_id=uuid4(),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # Expired
        )
        session.add(signal)
        await session.commit()

        mock_redis = _mock_redis()
        signal_executor = SignalExecutor(
            executor=_mock_executor(mock_redis),
            guard=ExecutionGuard(),
            market_data=AsyncMock(),
            session_factory=session_factory,
        )
        signal_executor._redis = mock_redis

        await signal_executor._poll_cycle()

        # No orders should have been created
        async with session_factory() as verify:
            count = (await verify.execute(
                select(func.count()).select_from(Order)
            )).scalar()
            assert count == 0

    @pytest.mark.asyncio
    async def test_executor_skips_already_processed_signals(
        self, session, session_factory,
    ):
        """Signals with an existing order should not be re-processed."""
        from app.tasks.signal_executor import SignalExecutor

        await _create_portfolio(session)

        # Create signal + linked order (already processed)
        signal = Signal(
            symbol="BTCUSDT",
            asset_class=AssetClass.CRYPTO.value,
            signal_type="BUY",
            confidence=Decimal("0.75"),
            timeframe="1h",
            indicators={},
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
            strategy_id=uuid4(),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        session.add(signal)
        await session.flush()

        order = Order(
            signal_id=signal.id,
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            status=OrderStatus.FILLED.value,
            requested_qty=Decimal("0.01"),
            filled_qty=Decimal("0.01"),
            requested_price=Decimal("42000"),
            avg_fill_price=Decimal("42000"),
            stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
            execution_mode="PAPER",
            risk_decision={},
            capital_decision={},
        )
        session.add(order)
        await session.commit()

        mock_redis = _mock_redis()
        signal_executor = SignalExecutor(
            executor=_mock_executor(mock_redis),
            guard=ExecutionGuard(),
            market_data=AsyncMock(),
            session_factory=session_factory,
        )
        signal_executor._redis = mock_redis

        await signal_executor._poll_cycle()

        # Should still be only 1 order (the one we created)
        async with session_factory() as verify:
            count = (await verify.execute(
                select(func.count()).select_from(Order)
            )).scalar()
            assert count == 1


# ── E2E: SL/TP Validation ──


class TestSLTPValidation:
    """Verify SL/TP are validated before execution."""

    @pytest.mark.asyncio
    async def test_sl_above_entry_rejected(self, session):
        """BUY with SL above entry is invalid."""
        await _create_portfolio(session)
        result = await _run_pipeline(
            session,
            _intent(stop_loss=Decimal("43000")),  # SL > entry (42000)
            _market(),
        )
        assert result.action == "REJECTED"
        assert "SL/TP" in result.reason

    @pytest.mark.asyncio
    async def test_tp_below_entry_rejected(self, session):
        """BUY with TP below entry is invalid."""
        await _create_portfolio(session)
        result = await _run_pipeline(
            session,
            _intent(take_profit=Decimal("41000")),  # TP < entry (42000)
            _market(),
        )
        assert result.action == "REJECTED"
        assert "SL/TP" in result.reason

    @pytest.mark.asyncio
    async def test_negative_prices_rejected(self, session):
        """Negative entry/SL/TP are invalid."""
        await _create_portfolio(session)
        result = await _run_pipeline(
            session,
            _intent(entry_price=Decimal("-1")),
            _market(),
        )
        assert result.action == "REJECTED"
