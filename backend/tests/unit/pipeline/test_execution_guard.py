from decimal import Decimal

import pytest

from app.pipeline.execution.guard import ExecutionGuard, MarketSnapshot


def _market(**overrides) -> MarketSnapshot:
    defaults = dict(
        symbol="BTCUSDT",
        price=Decimal("42000"),
        bid=Decimal("41990"),
        ask=Decimal("42010"),
        volume_24h=Decimal("500000"),
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


class TestExecutionGuard:
    @pytest.fixture
    def guard(self):
        return ExecutionGuard(
            max_price_drift_pct=Decimal("0.005"),
            max_spread_pct=Decimal("0.003"),
            min_volume_24h=Decimal("100000"),
        )

    @pytest.mark.asyncio
    async def test_approve_normal_conditions(self, guard):
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_market(),
        )
        assert result.approved

    @pytest.mark.asyncio
    async def test_reject_unfavorable_drift_buy(self, guard):
        """BUY: price went UP too much (unfavorable)."""
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_market(price=Decimal("42500")),  # +1.2%
            side="BUY",
        )
        assert not result.approved
        assert "drift" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_allow_favorable_drift_buy(self, guard):
        """BUY: price went DOWN (favorable) — allow even if > threshold."""
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_market(price=Decimal("41500")),  # -1.2% favorable
            side="BUY",
        )
        assert result.approved

    @pytest.mark.asyncio
    async def test_reject_wide_spread(self, guard):
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_market(bid=Decimal("41800"), ask=Decimal("42200")),
        )
        assert not result.approved
        assert "spread" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_reject_low_volume(self, guard):
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_market(volume_24h=Decimal("50000")),
        )
        assert not result.approved
        assert "volume" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_small_drift_approved(self, guard):
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_market(price=Decimal("42100")),
        )
        assert result.approved

    # Market sanity checks
    @pytest.mark.asyncio
    async def test_reject_zero_price(self, guard):
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_market(price=Decimal("0")),
        )
        assert not result.approved
        assert "invalid" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_reject_ask_below_bid(self, guard):
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_market(bid=Decimal("42100"), ask=Decimal("41900")),
        )
        assert not result.approved
        assert "corrupted" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_reject_negative_volume(self, guard):
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_market(volume_24h=Decimal("-100")),
        )
        assert not result.approved
