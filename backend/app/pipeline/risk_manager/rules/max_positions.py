from app.pipeline.risk_manager.rules.base import RiskContext, RiskDecision, RiskRule


class MaxPositionsRule(RiskRule):
    """Rejects new trades if maximum open positions reached."""

    def __init__(self, max_positions: int = 5):
        self._max_positions = max_positions

    @property
    def name(self) -> str:
        return "max_positions"

    async def evaluate(self, ctx: RiskContext) -> RiskDecision:
        if ctx.open_positions_count >= self._max_positions:
            return RiskDecision.reject(
                self.name,
                f"Open positions ({ctx.open_positions_count}) at maximum ({self._max_positions})",
                current=ctx.open_positions_count,
                maximum=self._max_positions,
            )
        return RiskDecision.approve(self.name)
