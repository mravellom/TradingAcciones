"""Tests for ExecutionGuard with stock-specific thresholds."""
from decimal import Decimal

import pytest

from app.pipeline.execution.guard import ExecutionGuard, MarketSnapshot


def _stock_market(**overrides) -> MarketSnapshot:
    defaults = dict(
        symbol="AAPL",
        price=Decimal("150.00"),
        bid=Decimal("149.98"),
        ask=Decimal("150.02"),
        volume_24h=Decimal("5000000"),
        asset_class="STOCKS",
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def _crypto_market(**overrides) -> MarketSnapshot:
    defaults = dict(
        symbol="BTCUSDT",
        price=Decimal("42000"),
        bid=Decimal("41990"),
        ask=Decimal("42010"),
        volume_24h=Decimal("500000"),
        asset_class="CRYPTO",
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


class TestGuardStockThresholds:
    @pytest.fixture
    def guard(self):
        return ExecutionGuard(
            # Crypto thresholds
            max_price_drift_pct=Decimal("0.005"),
            max_spread_pct=Decimal("0.003"),
            min_volume_24h=Decimal("100000"),
            # Stock thresholds (tighter)
            stock_max_price_drift_pct=Decimal("0.002"),
            stock_max_spread_pct=Decimal("0.001"),
            stock_min_volume_24h=Decimal("1000000"),
        )

    @pytest.mark.asyncio
    async def test_stock_approved_normal(self, guard):
        result = await guard.validate(
            order_price=Decimal("150.00"),
            order_quantity=Decimal("10"),
            market=_stock_market(),
        )
        assert result.approved

    @pytest.mark.asyncio
    async def test_stock_rejected_low_volume(self, guard):
        """Stocks need $1M+ volume, $500k should be rejected."""
        result = await guard.validate(
            order_price=Decimal("150.00"),
            order_quantity=Decimal("10"),
            market=_stock_market(volume_24h=Decimal("500000")),
        )
        assert not result.approved
        assert "volume" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_crypto_approved_at_500k_volume(self, guard):
        """Same volume ($500k) should pass for crypto."""
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_crypto_market(volume_24h=Decimal("500000")),
        )
        assert result.approved

    @pytest.mark.asyncio
    async def test_stock_tighter_drift(self, guard):
        """Stocks use 0.2% drift threshold, 0.3% drift should be rejected."""
        result = await guard.validate(
            order_price=Decimal("150.00"),
            order_quantity=Decimal("10"),
            market=_stock_market(price=Decimal("150.50")),  # +0.33% unfavorable
            side="BUY",
        )
        assert not result.approved
        assert "drift" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_crypto_allows_same_drift(self, guard):
        """Same 0.33% drift should pass for crypto (threshold 0.5%)."""
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=_crypto_market(price=Decimal("42140")),  # +0.33%
            side="BUY",
        )
        assert result.approved

    @pytest.mark.asyncio
    async def test_stock_tighter_spread(self, guard):
        """Stocks use 0.1% spread threshold."""
        result = await guard.validate(
            order_price=Decimal("150.00"),
            order_quantity=Decimal("10"),
            market=_stock_market(
                bid=Decimal("149.70"), ask=Decimal("150.30"),  # 0.4% spread
            ),
        )
        assert not result.approved
        assert "spread" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_default_asset_class_is_crypto(self, guard):
        """MarketSnapshot without asset_class should default to CRYPTO thresholds."""
        market = MarketSnapshot(
            symbol="BTCUSDT",
            price=Decimal("42000"),
            bid=Decimal("41990"),
            ask=Decimal("42010"),
            volume_24h=Decimal("500000"),
            # No asset_class — defaults to "CRYPTO"
        )
        result = await guard.validate(
            order_price=Decimal("42000"),
            order_quantity=Decimal("0.1"),
            market=market,
        )
        assert result.approved

    @pytest.mark.asyncio
    async def test_threshold_selection(self, guard):
        """Verify _thresholds method returns correct dict per asset class."""
        crypto_t = guard._thresholds("CRYPTO")
        stock_t = guard._thresholds("STOCKS")

        assert crypto_t["max_price_drift"] == Decimal("0.005")
        assert stock_t["max_price_drift"] == Decimal("0.002")
        assert crypto_t["min_volume"] == Decimal("100000")
        assert stock_t["min_volume"] == Decimal("1000000")
