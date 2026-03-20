from decimal import Decimal

from app.pipeline.risk_manager.rules.base import RiskContext, RiskDecision, RiskRule


class MaxExposurePerSymbolRule(RiskRule):
    """Rejects or reduces trade if it would exceed max exposure on a single symbol."""

    def __init__(self, max_exposure_pct: Decimal = Decimal("0.10")):
        self._max_exposure_pct = max_exposure_pct

    @property
    def name(self) -> str:
        return "max_exposure_per_symbol"

    async def evaluate(self, ctx: RiskContext) -> RiskDecision:
        if ctx.total_balance == 0:
            return RiskDecision.reject(self.name, "Zero balance")

        max_exposure = ctx.total_balance * self._max_exposure_pct
        remaining = max_exposure - ctx.symbol_exposure

        if remaining <= 0:
            return RiskDecision.reject(
                self.name,
                f"Symbol {ctx.symbol} already at max exposure "
                f"({ctx.symbol_exposure}/{max_exposure})",
                current_exposure=str(ctx.symbol_exposure),
                max_exposure=str(max_exposure),
            )

        return RiskDecision.approve(self.name)
