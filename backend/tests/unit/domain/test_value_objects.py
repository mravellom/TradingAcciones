from decimal import Decimal

import pytest

from app.domain.value_objects import ConfidenceScore, Money, Percentage, Price, Quantity


class TestMoney:
    def test_create_with_decimal(self):
        m = Money(amount=Decimal("100.50"))
        assert m.amount == Decimal("100.50")
        assert m.currency == "USDT"

    def test_create_with_float_converts_to_decimal(self):
        m = Money(amount=1.5)
        assert isinstance(m.amount, Decimal)

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError, match="negative"):
            Money(amount=Decimal("-1"))

    def test_add(self):
        a = Money(amount=Decimal("100"))
        b = Money(amount=Decimal("50"))
        result = a + b
        assert result.amount == Decimal("150")

    def test_sub(self):
        a = Money(amount=Decimal("100"))
        b = Money(amount=Decimal("30"))
        result = a - b
        assert result.amount == Decimal("70")

    def test_add_different_currency_raises(self):
        a = Money(amount=Decimal("100"), currency="USDT")
        b = Money(amount=Decimal("50"), currency="BTC")
        with pytest.raises(ValueError, match="Cannot add"):
            a + b

    def test_immutable(self):
        m = Money(amount=Decimal("100"))
        with pytest.raises(AttributeError):
            m.amount = Decimal("200")


class TestPercentage:
    def test_valid(self):
        p = Percentage(value=Decimal("0.5"))
        assert p.value == Decimal("0.5")

    def test_zero(self):
        p = Percentage(value=Decimal("0"))
        assert p.value == Decimal("0")

    def test_one(self):
        p = Percentage(value=Decimal("1"))
        assert p.value == Decimal("1")

    def test_above_one_raises(self):
        with pytest.raises(ValueError):
            Percentage(value=Decimal("1.1"))

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            Percentage(value=Decimal("-0.1"))


class TestConfidenceScore:
    def test_valid(self):
        c = ConfidenceScore(value=Decimal("0.75"))
        assert c.value == Decimal("0.75")

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            ConfidenceScore(value=Decimal("1.5"))


class TestPrice:
    def test_valid(self):
        p = Price(value=Decimal("42000.50"))
        assert p.value == Decimal("42000.50")

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            Price(value=Decimal("0"))

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            Price(value=Decimal("-1"))


class TestQuantity:
    def test_valid(self):
        q = Quantity(value=Decimal("0.5"))
        assert q.value == Decimal("0.5")

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            Quantity(value=Decimal("0"))
