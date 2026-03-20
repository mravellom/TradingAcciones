from decimal import Decimal

from app.domain.enums import RiskAction
from app.pipeline.risk_manager.rules.base import RiskContext, RiskDecision, RiskRule


class DailyLossLimitRule(RiskRule):
    """Rejects trades if daily loss exceeds limit. Halts system at 2x limit."""

    def __init__(self, max_daily_loss_pct: Decimal = Decimal("0.03")):
        self._max_daily_loss_pct = max_daily_loss_pct

    @property
    def name(self) -> str:
        return "daily_loss_limit"

    async def evaluate(self, ctx: RiskContext) -> RiskDecision:
        if ctx.total_balance == 0:
            return RiskDecision.reject(self.name, "Zero balance")

        daily_loss_pct = abs(min(ctx.daily_pnl, Decimal("0"))) / ctx.total_balance

        # HALT at 2x the limit
        halt_threshold = self._max_daily_loss_pct * 2
        if daily_loss_pct >= halt_threshold:
            return RiskDecision.halt(
                self.name,
                f"Daily loss {daily_loss_pct:.2%} exceeds halt threshold {halt_threshold:.2%}",
                daily_loss_pct=str(daily_loss_pct),
                threshold=str(halt_threshold),
            )

        # REJECT at limit
        if daily_loss_pct >= self._max_daily_loss_pct:
            return RiskDecision.reject(
                self.name,
                f"Daily loss {daily_loss_pct:.2%} exceeds limit {self._max_daily_loss_pct:.2%}",
                daily_loss_pct=str(daily_loss_pct),
                limit=str(self._max_daily_loss_pct),
            )

        return RiskDecision.approve(self.name)
