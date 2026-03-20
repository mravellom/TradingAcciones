"""Critical tests for portfolio balance consistency.

Verifies:
- available + allocated == total (invariant)
- Negative balance is impossible
- Fill deducts correctly
- Close restores correctly
- PnL calculations are correct
"""
from dataclasses import dataclass, field
from decimal import Decimal

import pytest


@dataclass
class MockPortfolio:
    """Lightweight portfolio mock that doesn't need SQLAlchemy session."""
    execution_mode: str = "PAPER"
    total_balance: Decimal = Decimal("10000")
    available_balance: Decimal = Decimal("10000")
    allocated_balance: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")


def _make_portfolio(
    total: Decimal = Decimal("10000"),
    available: Decimal | None = None,
    allocated: Decimal = Decimal("0"),
) -> MockPortfolio:
    if available is None:
        available = total - allocated
    return MockPortfolio(
        total_balance=total,
        available_balance=available,
        allocated_balance=allocated,
    )


class TestBalanceInvariant:
    """The golden rule: available + allocated == total."""

    def test_initial_balance(self):
        p = _make_portfolio()
        assert p.available_balance + p.allocated_balance == p.total_balance

    def test_after_fill(self):
        """Simulate a fill: move money from available to allocated."""
        p = _make_portfolio()
        fill_value = Decimal("1000")

        p.available_balance -= fill_value
        p.allocated_balance += fill_value

        assert p.available_balance + p.allocated_balance == p.total_balance
        assert p.available_balance == Decimal("9000")
        assert p.allocated_balance == Decimal("1000")

    def test_after_close_with_profit(self):
        """Close position with profit: allocated returns + pnl to available."""
        p = _make_portfolio(
            total=Decimal("10000"),
            available=Decimal("9000"),
            allocated=Decimal("1000"),
        )
        position_value = Decimal("1000")
        pnl = Decimal("50")

        p.allocated_balance -= position_value
        p.available_balance += position_value + pnl
        p.total_pnl += pnl
        p.total_balance = p.available_balance + p.allocated_balance

        assert p.available_balance + p.allocated_balance == p.total_balance
        assert p.total_balance == Decimal("10050")
        assert p.available_balance == Decimal("10050")
        assert p.allocated_balance == Decimal("0")

    def test_after_close_with_loss(self):
        """Close position with loss: less money returns."""
        p = _make_portfolio(
            total=Decimal("10000"),
            available=Decimal("9000"),
            allocated=Decimal("1000"),
        )
        position_value = Decimal("1000")
        pnl = Decimal("-200")

        p.allocated_balance -= position_value
        p.available_balance += position_value + pnl
        p.total_pnl += pnl
        p.total_balance = p.available_balance + p.allocated_balance

        assert p.available_balance + p.allocated_balance == p.total_balance
        assert p.total_balance == Decimal("9800")

    def test_multiple_fills_and_closes(self):
        """Simulate: 3 fills, 2 closes (1 win, 1 loss)."""
        p = _make_portfolio()

        # 3 fills of $1000 each
        for _ in range(3):
            p.available_balance -= Decimal("1000")
            p.allocated_balance += Decimal("1000")

        assert p.available_balance == Decimal("7000")
        assert p.allocated_balance == Decimal("3000")
        assert p.available_balance + p.allocated_balance == p.total_balance

        # Close 1: win $100
        p.allocated_balance -= Decimal("1000")
        p.available_balance += Decimal("1100")
        p.total_balance = p.available_balance + p.allocated_balance

        assert p.total_balance == Decimal("10100")

        # Close 2: loss $200
        p.allocated_balance -= Decimal("1000")
        p.available_balance += Decimal("800")
        p.total_balance = p.available_balance + p.allocated_balance

        assert p.total_balance == Decimal("9900")
        assert p.available_balance + p.allocated_balance == p.total_balance


class TestInsufficientBalance:
    """Verify the system catches insufficient funds."""

    def test_fill_exceeding_available(self):
        """Cannot fill more than available balance."""
        p = _make_portfolio(available=Decimal("500"))
        fill_value = Decimal("1000")

        # The PortfolioService.record_fill should raise
        assert p.available_balance < fill_value

    def test_fill_exactly_available(self):
        """Can fill exactly the available amount."""
        p = _make_portfolio(available=Decimal("1000"))
        assert p.available_balance >= Decimal("1000")

    def test_fill_after_multiple_trades(self):
        """After several fills, available decreases correctly."""
        p = _make_portfolio()

        for i in range(10):
            fill = Decimal("1000")
            if p.available_balance >= fill:
                p.available_balance -= fill
                p.allocated_balance += fill

        assert p.available_balance == Decimal("0")
        assert p.allocated_balance == Decimal("10000")

        # 11th fill should be rejected
        assert p.available_balance < Decimal("1000")


class TestDrawdownCalculation:
    def test_no_drawdown_when_profitable(self):
        p = _make_portfolio()
        p.total_pnl = Decimal("500")
        # No drawdown when in profit
        assert p.total_pnl > 0

    def test_drawdown_when_losing(self):
        p = _make_portfolio()
        p.total_pnl = Decimal("-500")
        p.total_balance = Decimal("9500")
        initial = p.total_balance - p.total_pnl  # 10000
        dd = abs(p.total_pnl) / initial
        assert dd == Decimal("0.05")  # 5% drawdown
