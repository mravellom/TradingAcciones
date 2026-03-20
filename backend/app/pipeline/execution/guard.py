"""Execution Guard — pre-execution validation.

Runs just before order submission to verify market conditions are safe.
Validates price drift, spread, volume, and market data sanity.
"""
from dataclasses import dataclass
from decimal import Decimal

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class GuardResult:
    approved: bool
    reason: str = ""
    adjusted_quantity: Decimal | None = None

    @staticmethod
    def approve() -> "GuardResult":
        return GuardResult(approved=True)

    @staticmethod
    def reject(reason: str) -> "GuardResult":
        return GuardResult(approved=False, reason=reason)

    @staticmethod
    def reduce(reason: str, max_qty: Decimal) -> "GuardResult":
        return GuardResult(approved=True, reason=reason, adjusted_quantity=max_qty)


@dataclass
class MarketSnapshot:
    symbol: str
    price: Decimal
    bid: Decimal
    ask: Decimal
    volume_24h: Decimal


class ExecutionGuard:
    """Pre-execution validation with market sanity checks."""

    def __init__(
        self,
        max_price_drift_pct: Decimal = Decimal("0.005"),
        max_spread_pct: Decimal = Decimal("0.003"),
        min_volume_24h: Decimal = Decimal("100000"),
    ):
        self._max_price_drift = max_price_drift_pct
        self._max_spread = max_spread_pct
        self._min_volume = min_volume_24h

    async def validate(
        self,
        order_price: Decimal,
        order_quantity: Decimal,
        market: MarketSnapshot,
        side: str = "BUY",
    ) -> GuardResult:
        """Validate market conditions just before execution."""

        # 0. Market data sanity checks
        sanity = self._check_market_sanity(market)
        if sanity:
            return GuardResult.reject(f"Market data invalid: {sanity}")

        # 1. Price drift check (directional)
        if order_price > 0:
            drift = (market.price - order_price) / order_price  # Signed drift
            abs_drift = abs(drift)

            if abs_drift > self._max_price_drift:
                # For BUY: positive drift (price went up) is unfavorable
                # For SELL: negative drift (price went down) is unfavorable
                unfavorable = (side == "BUY" and drift > 0) or (side == "SELL" and drift < 0)

                if unfavorable:
                    logger.info(
                        "guard_unfavorable_drift",
                        drift=f"{drift:.4%}",
                        side=side,
                        order_price=str(order_price),
                        market_price=str(market.price),
                    )
                    return GuardResult.reject(
                        f"Unfavorable price drift {drift:.2%} for {side} "
                        f"(max {self._max_price_drift:.2%})"
                    )
                # Favorable drift > threshold: log warning but allow
                logger.info(
                    "guard_favorable_drift",
                    drift=f"{drift:.4%}",
                    side=side,
                )

        # 2. Spread check
        if market.bid > 0:
            spread = (market.ask - market.bid) / market.bid
            if spread > self._max_spread:
                logger.info("guard_spread_wide", spread=f"{spread:.4%}")
                return GuardResult.reject(
                    f"Spread {spread:.2%} exceeds max {self._max_spread:.2%}"
                )

        # 3. Volume check
        if market.volume_24h < self._min_volume:
            logger.info("guard_low_volume", volume=str(market.volume_24h))
            return GuardResult.reject(
                f"24h volume {market.volume_24h} below minimum {self._min_volume}"
            )

        logger.info("guard_approved", symbol=market.symbol, side=side)
        return GuardResult.approve()

    @staticmethod
    def _check_market_sanity(market: MarketSnapshot) -> str | None:
        """Validate market data is reasonable. Returns error or None."""
        if market.price <= 0:
            return f"price={market.price} (must be > 0)"
        if market.bid <= 0:
            return f"bid={market.bid} (must be > 0)"
        if market.ask <= 0:
            return f"ask={market.ask} (must be > 0)"
        if market.ask < market.bid:
            return f"ask={market.ask} < bid={market.bid} (corrupted data)"
        if market.volume_24h < 0:
            return f"volume_24h={market.volume_24h} (must be >= 0)"
        return None
