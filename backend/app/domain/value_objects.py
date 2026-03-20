from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Money:
    """Represents a monetary amount. Always use Decimal, never float."""

    amount: Decimal
    currency: str = "USDT"

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", Decimal(str(self.amount)))
        if self.amount < 0:
            raise ValueError(f"Money amount cannot be negative: {self.amount}")

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot subtract {self.currency} and {other.currency}")
        return Money(amount=self.amount - other.amount, currency=self.currency)


@dataclass(frozen=True)
class Percentage:
    """Represents a percentage value (0.0 to 1.0)."""

    value: Decimal

    def __post_init__(self):
        if not isinstance(self.value, Decimal):
            object.__setattr__(self, "value", Decimal(str(self.value)))
        if not (Decimal("0") <= self.value <= Decimal("1")):
            raise ValueError(f"Percentage must be between 0 and 1: {self.value}")


@dataclass(frozen=True)
class ConfidenceScore:
    """Signal confidence score (0.0 to 1.0)."""

    value: Decimal

    def __post_init__(self):
        if not isinstance(self.value, Decimal):
            object.__setattr__(self, "value", Decimal(str(self.value)))
        if not (Decimal("0") <= self.value <= Decimal("1")):
            raise ValueError(f"Confidence must be between 0 and 1: {self.value}")


@dataclass(frozen=True)
class Price:
    """Represents a price. Always positive Decimal."""

    value: Decimal

    def __post_init__(self):
        if not isinstance(self.value, Decimal):
            object.__setattr__(self, "value", Decimal(str(self.value)))
        if self.value <= 0:
            raise ValueError(f"Price must be positive: {self.value}")


@dataclass(frozen=True)
class Quantity:
    """Represents a quantity. Always positive Decimal."""

    value: Decimal

    def __post_init__(self):
        if not isinstance(self.value, Decimal):
            object.__setattr__(self, "value", Decimal(str(self.value)))
        if self.value <= 0:
            raise ValueError(f"Quantity must be positive: {self.value}")
