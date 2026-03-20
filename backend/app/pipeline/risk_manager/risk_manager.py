from decimal import Decimal

from app.core.logging import get_logger
from app.domain.enums import RiskAction
from app.pipeline.risk_manager.circuit_breaker import CircuitBreaker
from app.pipeline.risk_manager.rules.base import RiskContext, RiskDecision, RiskRule

logger = get_logger(__name__)


class RiskManager:
    """Core risk gate. Evaluates all rules and can block or halt the system.

    Rules are evaluated in order. First rule that returns non-APPROVE stops evaluation.
    If any rule returns HALT_SYSTEM, the circuit breaker is activated.
    """

    def __init__(
        self,
        rules: list[RiskRule],
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self._rules = rules
        self._circuit_breaker = circuit_breaker or CircuitBreaker()

    async def validate(self, ctx: RiskContext) -> RiskDecision:
        """Evaluate all risk rules against the given context.

        Returns:
            RiskDecision with APPROVE, REJECT, REDUCE_SIZE, or HALT_SYSTEM.
        """
        # Check circuit breaker first
        if await self._circuit_breaker.is_active():
            return RiskDecision.reject(
                rule="circuit_breaker",
                reason="Circuit breaker is active. System halted.",
            )

        # Evaluate each rule
        for rule in self._rules:
            try:
                decision = await rule.evaluate(ctx)
            except Exception as e:
                logger.error(
                    "risk_rule_error",
                    rule=rule.name,
                    error=str(e),
                )
                # Rule error = reject for safety
                return RiskDecision.reject(
                    rule=rule.name,
                    reason=f"Rule evaluation error: {e}",
                )

            if decision.action == RiskAction.HALT_SYSTEM:
                await self._circuit_breaker.activate(
                    reason=f"[{decision.rule}] {decision.reason}"
                )
                logger.warning(
                    "risk_halt_system",
                    rule=decision.rule,
                    reason=decision.reason,
                )
                return decision

            if decision.action in (RiskAction.REJECT, RiskAction.REDUCE_SIZE):
                logger.info(
                    "risk_rejected",
                    rule=decision.rule,
                    action=decision.action.value,
                    reason=decision.reason,
                    symbol=ctx.symbol,
                )
                return decision

        logger.info(
            "risk_approved",
            symbol=ctx.symbol,
            confidence=str(ctx.confidence),
            rules_passed=len(self._rules),
        )
        return RiskDecision.approve()

    def add_rule(self, rule: RiskRule) -> None:
        self._rules.append(rule)

    def remove_rule(self, rule_name: str) -> None:
        self._rules = [r for r in self._rules if r.name != rule_name]

    @staticmethod
    def create_default(
        max_daily_loss_pct: Decimal = Decimal("0.03"),
        max_drawdown_pct: Decimal = Decimal("0.10"),
        min_confidence: Decimal = Decimal("0.6"),
        max_positions: int = 5,
        max_exposure_pct: Decimal = Decimal("0.10"),
    ) -> "RiskManager":
        """Factory method to create a RiskManager with default rules."""
        from app.pipeline.risk_manager.rules import (
            DailyLossLimitRule,
            MaxDrawdownRule,
            MaxExposurePerSymbolRule,
            MaxPositionsRule,
            MinConfidenceRule,
        )

        return RiskManager(
            rules=[
                MinConfidenceRule(min_confidence),
                DailyLossLimitRule(max_daily_loss_pct),
                MaxDrawdownRule(max_drawdown_pct),
                MaxPositionsRule(max_positions),
                MaxExposurePerSymbolRule(max_exposure_pct),
            ]
        )
