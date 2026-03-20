from decimal import Decimal

import pytest

from app.pipeline.capital_manager.capital_manager import CapitalManager


class TestCapitalManager:
    @pytest.fixture
    def cm(self):
        return CapitalManager(
            risk_per_trade_pct=Decimal("0.01"),
            max_exposure_per_symbol_pct=Decimal("0.10"),
            min_notional=Decimal("10"),
        )

    def test_basic_sizing(self, cm):
        sizing = cm.calculate_size(
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41580"),     # 1% distance
            confidence=Decimal("0.8"),
            total_balance=Decimal("10000"),
            available_balance=Decimal("10000"),
        )
        assert sizing is not None
        assert sizing.quantity > 0
        assert sizing.risk_amount > 0
        assert sizing.position_value > 0

    def test_risk_amount_scales_with_confidence(self):
        # Use high max_exposure to avoid cap interference
        cm = CapitalManager(
            risk_per_trade_pct=Decimal("0.01"),
            max_exposure_per_symbol_pct=Decimal("1.0"),  # No cap
            min_notional=Decimal("10"),
        )
        high = cm.calculate_size(
            entry_price=Decimal("100"),
            stop_loss=Decimal("99"),
            confidence=Decimal("0.9"),
            total_balance=Decimal("10000"),
            available_balance=Decimal("10000"),
        )
        low = cm.calculate_size(
            entry_price=Decimal("100"),
            stop_loss=Decimal("99"),
            confidence=Decimal("0.6"),
            total_balance=Decimal("10000"),
            available_balance=Decimal("10000"),
        )
        assert high.quantity > low.quantity

    def test_max_exposure_constraint(self, cm):
        # Already at 900 of 1000 max (10% of 10000)
        sizing = cm.calculate_size(
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41580"),
            confidence=Decimal("0.9"),
            total_balance=Decimal("10000"),
            available_balance=Decimal("10000"),
            symbol_exposure=Decimal("900"),
        )
        assert sizing is not None
        # Position value should not exceed remaining 100
        assert sizing.position_value <= Decimal("100.00000001")

    def test_max_exposure_fully_used(self, cm):
        sizing = cm.calculate_size(
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41580"),
            confidence=Decimal("0.9"),
            total_balance=Decimal("10000"),
            available_balance=Decimal("10000"),
            symbol_exposure=Decimal("1000"),  # Already at max
        )
        assert sizing is None

    def test_zero_balance_returns_none(self, cm):
        sizing = cm.calculate_size(
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41580"),
            confidence=Decimal("0.8"),
            total_balance=Decimal("0"),
            available_balance=Decimal("0"),
        )
        assert sizing is None

    def test_zero_sl_distance_returns_none(self, cm):
        sizing = cm.calculate_size(
            entry_price=Decimal("42000"),
            stop_loss=Decimal("42000"),  # Same as entry = 0 distance
            confidence=Decimal("0.8"),
            total_balance=Decimal("10000"),
            available_balance=Decimal("10000"),
        )
        assert sizing is None

    def test_below_min_notional_returns_none(self):
        cm = CapitalManager(
            risk_per_trade_pct=Decimal("0.0001"),  # Very small risk
            min_notional=Decimal("10"),
        )
        sizing = cm.calculate_size(
            entry_price=Decimal("42000"),
            stop_loss=Decimal("41580"),
            confidence=Decimal("0.6"),
            total_balance=Decimal("100"),   # Small balance
            available_balance=Decimal("100"),
        )
        # With 0.01% risk on $100 = $0.006 risk, position too small
        assert sizing is None

    def test_available_balance_constraint(self, cm):
        sizing = cm.calculate_size(
            entry_price=Decimal("100"),
            stop_loss=Decimal("99"),      # 1% distance
            confidence=Decimal("0.9"),
            total_balance=Decimal("10000"),
            available_balance=Decimal("50"),  # Very low available
        )
        assert sizing is not None
        assert sizing.position_value <= Decimal("50.00000001")

    def test_wider_stop_loss_means_smaller_position(self):
        # Use high max_exposure to avoid cap interference
        cm = CapitalManager(
            risk_per_trade_pct=Decimal("0.01"),
            max_exposure_per_symbol_pct=Decimal("1.0"),  # No cap
            min_notional=Decimal("10"),
        )
        tight = cm.calculate_size(
            entry_price=Decimal("100"),
            stop_loss=Decimal("99"),        # 1% SL
            confidence=Decimal("0.8"),
            total_balance=Decimal("10000"),
            available_balance=Decimal("10000"),
        )
        wide = cm.calculate_size(
            entry_price=Decimal("100"),
            stop_loss=Decimal("97"),        # 3% SL
            confidence=Decimal("0.8"),
            total_balance=Decimal("10000"),
            available_balance=Decimal("10000"),
        )
        # Wider SL = smaller quantity (same risk amount, spread over more distance)
        assert tight.quantity > wide.quantity
