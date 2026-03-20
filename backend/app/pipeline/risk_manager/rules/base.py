from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.enums import RiskAction


@dataclass
class RiskDecision:
    """Result of a risk rule evaluation."""

    action: RiskAction
    rule: str = ""
    reason: str = ""
    details: dict = field(default_factory=dict)

    @staticmethod
    def approve(rule: str = "") -> "RiskDecision":
        return RiskDecision(action=RiskAction.APPROVE, rule=rule)

    @staticmethod
    def reject(rule: str, reason: str, **details) -> "RiskDecision":
        return RiskDecision(
            action=RiskAction.REJECT, rule=rule, reason=reason, details=details
        )

    @staticmethod
    def reduce_size(rule: str, reason: str, max_qty: Decimal) -> "RiskDecision":
        return RiskDecision(
            action=RiskAction.REDUCE_SIZE,
            rule=rule,
            reason=reason,
            details={"max_qty": str(max_qty)},
        )

    @staticmethod
    def halt(rule: str, reason: str, **details) -> "RiskDecision":
        return RiskDecision(
            action=RiskAction.HALT_SYSTEM, rule=rule, reason=reason, details=details
        )


@dataclass
class RiskContext:
    """All data needed for risk evaluation."""

    symbol: str
    signal_type: str  # BUY / SELL
    confidence: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    strategy_id: str

    # Portfolio state
    total_balance: Decimal
    available_balance: Decimal
    daily_pnl: Decimal
    max_drawdown: Decimal

    # Position state
    open_positions_count: int
    symbol_exposure: Decimal  # current exposure on this symbol


class RiskRule(ABC):
    """Abstract base for individual risk rules."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Rule identifier."""

    @abstractmethod
    async def evaluate(self, ctx: RiskContext) -> RiskDecision:
        """Evaluate the rule. Return APPROVE if OK, REJECT/HALT otherwise."""
