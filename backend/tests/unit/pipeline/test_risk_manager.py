from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.domain.enums import RiskAction
from app.pipeline.risk_manager.risk_manager import RiskManager
from app.pipeline.risk_manager.rules.base import RiskContext, RiskDecision, RiskRule


def _ctx(**overrides) -> RiskContext:
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


class AlwaysApproveRule(RiskRule):
    @property
    def name(self):
        return "always_approve"

    async def evaluate(self, ctx):
        return RiskDecision.approve(self.name)


class AlwaysRejectRule(RiskRule):
    @property
    def name(self):
        return "always_reject"

    async def evaluate(self, ctx):
        return RiskDecision.reject(self.name, "Test rejection")


class AlwaysHaltRule(RiskRule):
    @property
    def name(self):
        return "always_halt"

    async def evaluate(self, ctx):
        return RiskDecision.halt(self.name, "Test halt")


class ExplodingRule(RiskRule):
    @property
    def name(self):
        return "exploding"

    async def evaluate(self, ctx):
        raise RuntimeError("Rule exploded")


class TestRiskManager:
    @pytest.mark.asyncio
    async def test_all_rules_approve(self):
        cb = AsyncMock()
        cb.is_active = AsyncMock(return_value=False)
        manager = RiskManager(
            rules=[AlwaysApproveRule(), AlwaysApproveRule()],
            circuit_breaker=cb,
        )
        decision = await manager.validate(_ctx())
        assert decision.action == RiskAction.APPROVE

    @pytest.mark.asyncio
    async def test_first_reject_stops_evaluation(self):
        cb = AsyncMock()
        cb.is_active = AsyncMock(return_value=False)
        second_rule = AlwaysApproveRule()

        manager = RiskManager(
            rules=[AlwaysRejectRule(), second_rule],
            circuit_breaker=cb,
        )
        decision = await manager.validate(_ctx())
        assert decision.action == RiskAction.REJECT
        assert decision.rule == "always_reject"

    @pytest.mark.asyncio
    async def test_halt_activates_circuit_breaker(self):
        cb = AsyncMock()
        cb.is_active = AsyncMock(return_value=False)
        cb.activate = AsyncMock()

        manager = RiskManager(
            rules=[AlwaysHaltRule()],
            circuit_breaker=cb,
        )
        decision = await manager.validate(_ctx())
        assert decision.action == RiskAction.HALT_SYSTEM
        cb.activate.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_breaker_active_rejects_immediately(self):
        cb = AsyncMock()
        cb.is_active = AsyncMock(return_value=True)

        manager = RiskManager(
            rules=[AlwaysApproveRule()],
            circuit_breaker=cb,
        )
        decision = await manager.validate(_ctx())
        assert decision.action == RiskAction.REJECT
        assert "circuit_breaker" in decision.rule

    @pytest.mark.asyncio
    async def test_rule_error_rejects_for_safety(self):
        cb = AsyncMock()
        cb.is_active = AsyncMock(return_value=False)

        manager = RiskManager(
            rules=[ExplodingRule()],
            circuit_breaker=cb,
        )
        decision = await manager.validate(_ctx())
        assert decision.action == RiskAction.REJECT
        assert "error" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_create_default(self):
        manager = RiskManager.create_default()
        assert len(manager._rules) == 5

    @pytest.mark.asyncio
    async def test_add_remove_rule(self):
        cb = AsyncMock()
        cb.is_active = AsyncMock(return_value=False)
        manager = RiskManager(rules=[], circuit_breaker=cb)

        manager.add_rule(AlwaysApproveRule())
        assert len(manager._rules) == 1

        manager.remove_rule("always_approve")
        assert len(manager._rules) == 0
