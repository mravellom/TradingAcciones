from collections import Counter
from decimal import Decimal

from app.core.logging import get_logger
from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.signal_engine.base import SignalGenerator, SignalResult

logger = get_logger(__name__)


class CompositeSignalGenerator:
    """Combines multiple signal generators into a single weighted signal.

    Rules:
    - If min_agreeing_signals >= total generators (or None): all must agree (unanimous).
    - If min_agreeing_signals < total: partial agreement allowed — the majority
      direction is used if it has at least min_agreeing_signals votes.
    - Only returns a signal if combined confidence >= min_confidence.
    """

    def __init__(
        self,
        generators: list[tuple[SignalGenerator, float]],  # (generator, weight)
        min_confidence: Decimal = Decimal("0.6"),
        min_agreeing_signals: int | None = None,
    ):
        total_weight = sum(w for _, w in generators)
        # Normalize weights
        self._generators = [
            (gen, w / total_weight) for gen, w in generators
        ]
        self._min_confidence = min_confidence
        self._min_agreeing = min_agreeing_signals

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

        # Check agreement
        signal_types = {r.signal_type for r, _ in results}

        if len(signal_types) > 1:
            # Disagreement — check if partial agreement is allowed
            total_generators = len(self._generators)
            min_needed = self._min_agreeing if self._min_agreeing is not None else total_generators

            if min_needed >= total_generators:
                # Unanimous required but disagreement found
                logger.info(
                    "signal_disagreement",
                    symbol=symbol,
                    types=[str(t) for t in signal_types],
                )
                return None

            # Count votes per direction
            votes: Counter[SignalType] = Counter()
            for r, _ in results:
                votes[r.signal_type] += 1

            majority_type, majority_count = votes.most_common(1)[0]

            if majority_count < min_needed:
                logger.info(
                    "signal_partial_agreement_insufficient",
                    symbol=symbol,
                    votes=dict(votes),
                    min_needed=min_needed,
                )
                return None

            # Filter to only agreeing generators
            excluded = [
                gen.name for gen, _ in self._generators
                if any(r.signal_type != majority_type for r, _ in results if id(r) == id(r))
            ]
            agreeing = [(r, w) for r, w in results if r.signal_type == majority_type]
            excluded_names = [r.indicators.get("generator", "unknown")
                             for r, _ in results if r.signal_type != majority_type]

            logger.info(
                "signal_partial_agreement_accepted",
                symbol=symbol,
                direction=majority_type.value,
                agreeing=majority_count,
                total=len(results),
                excluded=excluded_names,
            )

            results = agreeing

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
