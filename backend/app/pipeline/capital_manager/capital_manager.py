from dataclasses import dataclass
from decimal import Decimal

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Sizing:
    """Result of capital allocation."""

    quantity: Decimal
    risk_amount: Decimal  # How much we're risking on this trade
    position_value: Decimal  # Total value of the position


class CapitalManager:
    """Calculates position sizing based on risk management principles.

    Formula:
        risk_amount = available_balance * risk_per_trade * confidence
        quantity = risk_amount / (entry_price * distance_to_stop_loss)

    Constraints:
        - Never exceed max_exposure_per_symbol
        - Never use more than available_balance
        - Respect exchange minimum notional
    """

    def __init__(
        self,
        risk_per_trade_pct: Decimal = Decimal("0.01"),
        max_exposure_per_symbol_pct: Decimal = Decimal("0.10"),
        min_notional: Decimal = Decimal("10"),  # Binance min order value
    ):
        self._risk_per_trade_pct = risk_per_trade_pct
        self._max_exposure_pct = max_exposure_per_symbol_pct
        self._min_notional = min_notional

    def calculate_size(
        self,
        entry_price: Decimal,
        stop_loss: Decimal,
        confidence: Decimal,
        total_balance: Decimal,
        available_balance: Decimal,
        symbol_exposure: Decimal = Decimal("0"),
    ) -> Sizing | None:
        """Calculate position size.

        Returns None if the trade is too small or impossible.
        """
        if entry_price <= 0 or total_balance <= 0 or available_balance <= 0:
            return None

        # Distance to stop loss as percentage
        distance = abs(entry_price - stop_loss) / entry_price
        if distance == 0:
            logger.warning("capital_zero_sl_distance", entry=str(entry_price), sl=str(stop_loss))
            return None

        # Risk amount: what we're willing to lose
        risk_amount = available_balance * self._risk_per_trade_pct * confidence

        # Position value based on risk
        position_value = risk_amount / distance

        # Constraint: max exposure per symbol
        max_exposure = total_balance * self._max_exposure_pct
        remaining_exposure = max_exposure - symbol_exposure
        if remaining_exposure <= 0:
            logger.info("capital_max_exposure_reached", symbol_exposure=str(symbol_exposure))
            return None

        position_value = min(position_value, remaining_exposure)

        # Constraint: don't exceed available balance
        position_value = min(position_value, available_balance)

        # Calculate quantity
        quantity = position_value / entry_price

        # Check minimum notional
        if position_value < self._min_notional:
            logger.info(
                "capital_below_min_notional",
                position_value=str(position_value),
                min_notional=str(self._min_notional),
            )
            return None

        # Recalculate actual risk amount after constraints
        actual_risk = quantity * entry_price * distance

        logger.info(
            "capital_sized",
            quantity=str(quantity),
            position_value=str(position_value),
            risk_amount=str(actual_risk),
            distance_pct=f"{distance:.4%}",
        )

        return Sizing(
            quantity=quantity.quantize(Decimal("0.00000001")),
            risk_amount=actual_risk.quantize(Decimal("0.00000001")),
            position_value=position_value.quantize(Decimal("0.00000001")),
        )
