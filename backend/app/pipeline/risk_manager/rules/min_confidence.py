from decimal import Decimal

from app.pipeline.risk_manager.rules.base import RiskContext, RiskDecision, RiskRule


class MinConfidenceRule(RiskRule):
    """Rejects signals below minimum confidence threshold."""

    def __init__(self, min_confidence: Decimal = Decimal("0.6")):
        self._min_confidence = min_confidence

    @property
    def name(self) -> str:
        return "min_confidence"

    async def evaluate(self, ctx: RiskContext) -> RiskDecision:
        if ctx.confidence < self._min_confidence:
            return RiskDecision.reject(
                self.name,
                f"Confidence {ctx.confidence} below minimum {self._min_confidence}",
                confidence=str(ctx.confidence),
                minimum=str(self._min_confidence),
            )
        return RiskDecision.approve(self.name)
