from decimal import Decimal

import pytest

from app.domain.enums import RiskAction
from app.pipeline.risk_manager.rules import (
    DailyLossLimitRule,
    MaxDrawdownRule,
    MaxExposurePerSymbolRule,
    MaxPositionsRule,
    MinConfidenceRule,
    RiskContext,
)


def _ctx(**overrides) -> RiskContext:
    """Create a default RiskContext with overrides."""
    defaults = dict(
        symbol="BTCUSDT",
        signal_type="BUY",
        confidence=Decimal("0.75"),
        entry_price=Decimal("42000"),
        stop_loss=Decimal("41000"),
        take_profit=Decimal("44000"),
        strategy_id="test-strategy",
        total_balance=Decimal("10000"),
        available_balance=Decimal("8000"),
        daily_pnl=Decimal("0"),
        max_drawdown=Decimal("0"),
        open_positions_count=0,
        symbol_exposure=Decimal("0"),
    )
    defaults.update(overrides)
    return RiskContext(**defaults)


# ── Daily Loss Limit ──


class TestDailyLossLimit:
    @pytest.mark.asyncio
    async def test_approve_no_loss(self):
        rule = DailyLossLimitRule(max_daily_loss_pct=Decimal("0.03"))
        decision = await rule.evaluate(_ctx(daily_pnl=Decimal("100")))
        assert decision.action == RiskAction.APPROVE

    @pytest.mark.asyncio
    async def test_approve_small_loss(self):
        rule = DailyLossLimitRule(max_daily_loss_pct=Decimal("0.03"))
        decision = await rule.evaluate(_ctx(daily_pnl=Decimal("-200")))  # 2% of 10000
        assert decision.action == RiskAction.APPROVE

    @pytest.mark.asyncio
    async def test_reject_at_limit(self):
        rule = DailyLossLimitRule(max_daily_loss_pct=Decimal("0.03"))
        decision = await rule.evaluate(_ctx(daily_pnl=Decimal("-300")))  # 3%
        assert decision.action == RiskAction.REJECT
        assert decision.rule == "daily_loss_limit"

    @pytest.mark.asyncio
    async def test_halt_at_double_limit(self):
        rule = DailyLossLimitRule(max_daily_loss_pct=Decimal("0.03"))
        decision = await rule.evaluate(_ctx(daily_pnl=Decimal("-600")))  # 6% = 2x limit
        assert decision.action == RiskAction.HALT_SYSTEM

    @pytest.mark.asyncio
    async def test_reject_zero_balance(self):
        rule = DailyLossLimitRule()
        decision = await rule.evaluate(_ctx(total_balance=Decimal("0")))
        assert decision.action == RiskAction.REJECT


# ── Max Drawdown ──


class TestMaxDrawdown:
    @pytest.mark.asyncio
    async def test_approve_no_drawdown(self):
        rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))
        decision = await rule.evaluate(_ctx(max_drawdown=Decimal("0.02")))
        assert decision.action == RiskAction.APPROVE

    @pytest.mark.asyncio
    async def test_reject_approaching_limit(self):
        rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))
        decision = await rule.evaluate(_ctx(max_drawdown=Decimal("0.08")))  # 80% of limit
        assert decision.action == RiskAction.REJECT

    @pytest.mark.asyncio
    async def test_halt_at_limit(self):
        rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))
        decision = await rule.evaluate(_ctx(max_drawdown=Decimal("0.10")))
        assert decision.action == RiskAction.HALT_SYSTEM

    @pytest.mark.asyncio
    async def test_halt_above_limit(self):
        rule = MaxDrawdownRule(max_drawdown_pct=Decimal("0.10"))
        decision = await rule.evaluate(_ctx(max_drawdown=Decimal("0.15")))
        assert decision.action == RiskAction.HALT_SYSTEM


# ── Min Confidence ──


class TestMinConfidence:
    @pytest.mark.asyncio
    async def test_approve_above_minimum(self):
        rule = MinConfidenceRule(min_confidence=Decimal("0.6"))
        decision = await rule.evaluate(_ctx(confidence=Decimal("0.75")))
        assert decision.action == RiskAction.APPROVE

    @pytest.mark.asyncio
    async def test_approve_at_minimum(self):
        rule = MinConfidenceRule(min_confidence=Decimal("0.6"))
        decision = await rule.evaluate(_ctx(confidence=Decimal("0.6")))
        assert decision.action == RiskAction.APPROVE

    @pytest.mark.asyncio
    async def test_reject_below_minimum(self):
        rule = MinConfidenceRule(min_confidence=Decimal("0.6"))
        decision = await rule.evaluate(_ctx(confidence=Decimal("0.55")))
        assert decision.action == RiskAction.REJECT
        assert decision.rule == "min_confidence"


# ── Max Positions ──


class TestMaxPositions:
    @pytest.mark.asyncio
    async def test_approve_below_max(self):
        rule = MaxPositionsRule(max_positions=5)
        decision = await rule.evaluate(_ctx(open_positions_count=3))
        assert decision.action == RiskAction.APPROVE

    @pytest.mark.asyncio
    async def test_reject_at_max(self):
        rule = MaxPositionsRule(max_positions=5)
        decision = await rule.evaluate(_ctx(open_positions_count=5))
        assert decision.action == RiskAction.REJECT
        assert decision.rule == "max_positions"

    @pytest.mark.asyncio
    async def test_reject_above_max(self):
        rule = MaxPositionsRule(max_positions=5)
        decision = await rule.evaluate(_ctx(open_positions_count=7))
        assert decision.action == RiskAction.REJECT


# ── Max Exposure Per Symbol ──


class TestMaxExposure:
    @pytest.mark.asyncio
    async def test_approve_no_exposure(self):
        rule = MaxExposurePerSymbolRule(max_exposure_pct=Decimal("0.10"))
        decision = await rule.evaluate(_ctx(symbol_exposure=Decimal("0")))
        assert decision.action == RiskAction.APPROVE

    @pytest.mark.asyncio
    async def test_approve_below_limit(self):
        rule = MaxExposurePerSymbolRule(max_exposure_pct=Decimal("0.10"))
        decision = await rule.evaluate(_ctx(symbol_exposure=Decimal("500")))  # 5% of 10000
        assert decision.action == RiskAction.APPROVE

    @pytest.mark.asyncio
    async def test_reject_at_limit(self):
        rule = MaxExposurePerSymbolRule(max_exposure_pct=Decimal("0.10"))
        decision = await rule.evaluate(_ctx(symbol_exposure=Decimal("1000")))  # 10%
        assert decision.action == RiskAction.REJECT
        assert decision.rule == "max_exposure_per_symbol"

    @pytest.mark.asyncio
    async def test_reject_zero_balance(self):
        rule = MaxExposurePerSymbolRule()
        decision = await rule.evaluate(_ctx(total_balance=Decimal("0")))
        assert decision.action == RiskAction.REJECT
