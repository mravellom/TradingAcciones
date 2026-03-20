from decimal import Decimal

from app.pipeline.risk_manager.rules.base import RiskContext, RiskDecision, RiskRule


class MaxDrawdownRule(RiskRule):
    """Halts system if maximum drawdown exceeds threshold."""

    def __init__(self, max_drawdown_pct: Decimal = Decimal("0.10")):
        self._max_drawdown_pct = max_drawdown_pct

    @property
    def name(self) -> str:
        return "max_drawdown"

    async def evaluate(self, ctx: RiskContext) -> RiskDecision:
        if ctx.max_drawdown >= self._max_drawdown_pct:
            return RiskDecision.halt(
                self.name,
                f"Max drawdown {ctx.max_drawdown:.2%} exceeds limit {self._max_drawdown_pct:.2%}",
                current_drawdown=str(ctx.max_drawdown),
                limit=str(self._max_drawdown_pct),
            )

        # Warn (reject) at 80% of limit
        warn_threshold = self._max_drawdown_pct * Decimal("0.8")
        if ctx.max_drawdown >= warn_threshold:
            return RiskDecision.reject(
                self.name,
                f"Drawdown {ctx.max_drawdown:.2%} approaching limit (>{warn_threshold:.2%})",
                current_drawdown=str(ctx.max_drawdown),
                warn_threshold=str(warn_threshold),
            )

        return RiskDecision.approve(self.name)
