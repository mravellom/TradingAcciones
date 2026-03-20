from decimal import Decimal

from app.core.logging import get_logger
from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.signal_engine.base import SignalGenerator, SignalResult

logger = get_logger(__name__)


class CompositeSignalGenerator:
    """Combines multiple signal generators into a single weighted signal.

    Rules:
    - If generators disagree (BUY vs SELL), return None (no signal).
    - If generators agree, combine confidence as weighted average.
    - Only returns a signal if combined confidence >= min_confidence.
    """

    def __init__(
        self,
        generators: list[tuple[SignalGenerator, float]],  # (generator, weight)
        min_confidence: Decimal = Decimal("0.6"),
    ):
        total_weight = sum(w for _, w in generators)
        # Normalize weights
        self._generators = [
            (gen, w / total_weight) for gen, w in generators
        ]
        self._min_confidence = min_confidence

    async def generate(self, symbol: str, klines: list[Kline]) -> SignalResult | None:
        """Run all generators and combine results."""
        results: list[tuple[SignalResult, float]] = []

        for generator, weight in self._generators:
            try:
                result = await generator.generate(symbol, klines)
                if result and result.signal_type != SignalType.HOLD:
                    results.append((result, weight))
            except Exception as e:
                logger.error(
                    "signal_generator_error",
                    generator=generator.name,
                    symbol=symbol,
                    error=str(e),
                )

        if not results:
            return None

        # Check agreement: all signals must be the same type
        signal_types = {r.signal_type for r, _ in results}
        if len(signal_types) > 1:
            logger.info(
                "signal_disagreement",
                symbol=symbol,
                types=[str(t) for t in signal_types],
            )
            return None

        signal_type = results[0][0].signal_type

        # Re-normalize weights for responding generators only
        total_weight = sum(w for _, w in results)
        combined_confidence = sum(
            float(r.confidence) * (w / total_weight) for r, w in results
        )
        confidence = Decimal(str(round(combined_confidence, 4)))

        if confidence < self._min_confidence:
            return None

        # Use the highest-confidence result for entry/SL/TP
        best_result = max(results, key=lambda x: x[0].confidence)[0]

        # Merge all indicators
        all_indicators = {}
        for r, _ in results:
            all_indicators.update(r.indicators)

        return SignalResult(
            symbol=symbol,
            signal_type=signal_type,
            confidence=confidence,
            indicators=all_indicators,
            entry_price=best_result.entry_price,
            stop_loss=best_result.stop_loss,
            take_profit=best_result.take_profit,
        )
