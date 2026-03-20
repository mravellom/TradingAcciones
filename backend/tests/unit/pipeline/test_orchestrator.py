"""Critical tests for TradingPipeline orchestrator.

Tests SL/TP validation, balance checks, and pipeline flow logic.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.enums import SignalType
from app.pipeline.execution.guard import MarketSnapshot
from app.pipeline.orchestrator import PipelineResult, _validate_sl_tp
from app.pipeline.strategy.base import TradeIntent


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
