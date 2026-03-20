import asyncio
from collections import defaultdict

from app.core.logging import get_logger
from app.exchange.base import Kline
from app.pipeline.strategy.base import Strategy, TradeIntent

logger = get_logger(__name__)

DEFAULT_STRATEGY_TIMEOUT = 5  # seconds
MAX_CONSECUTIVE_FAILURES = 3


class StrategyRunner:
    """Runs multiple strategies in isolation with error handling.

    - Each strategy runs in its own asyncio.Task with a timeout.
    - A failing strategy does NOT affect others.
    - Auto-deactivates after MAX_CONSECUTIVE_FAILURES.
    """

    def __init__(self, timeout: int = DEFAULT_STRATEGY_TIMEOUT):
        self._timeout = timeout
        self._failure_counts: dict[str, int] = defaultdict(int)
        self._deactivated: set[str] = set()

    async def run_all(
        self,
        strategies: list[Strategy],
        symbol: str,
        klines: list[Kline],
        timeframe: str,
    ) -> list[TradeIntent]:
        """Run all active strategies in parallel, return valid intents."""
        active = [s for s in strategies if str(s.id) not in self._deactivated]

        if not active:
            return []

        tasks = [
            self._run_one(s, symbol, klines, timeframe) for s in active
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        intents = []
        for strategy, result in zip(active, results):
            if isinstance(result, Exception):
                logger.error(
                    "strategy_exception",
                    strategy=strategy.name,
                    strategy_id=str(strategy.id),
                    error=str(result),
                )
                continue
            if result is not None:
                intents.append(result)

        return intents

    async def _run_one(
        self,
        strategy: Strategy,
        symbol: str,
        klines: list[Kline],
        timeframe: str,
    ) -> TradeIntent | None:
        """Run a single strategy with timeout and failure tracking."""
        sid = str(strategy.id)
        try:
            async with asyncio.timeout(self._timeout):
                result = await strategy.evaluate(symbol, klines, timeframe)
            # Reset failure count on success
            self._failure_counts[sid] = 0
            return result
        except TimeoutError:
            logger.warning(
                "strategy_timeout",
                strategy=strategy.name,
                timeout=self._timeout,
            )
            self._record_failure(strategy)
            return None
        except Exception as e:
            logger.error(
                "strategy_failed",
                strategy=strategy.name,
                error=str(e),
            )
            self._record_failure(strategy)
            return None

    def _record_failure(self, strategy: Strategy) -> None:
        sid = str(strategy.id)
        self._failure_counts[sid] += 1
        if self._failure_counts[sid] >= MAX_CONSECUTIVE_FAILURES:
            self._deactivated.add(sid)
            logger.warning(
                "strategy_auto_deactivated",
                strategy=strategy.name,
                strategy_id=sid,
                consecutive_failures=self._failure_counts[sid],
            )

    def reactivate(self, strategy_id: str) -> None:
        """Manually reactivate a deactivated strategy."""
        self._deactivated.discard(strategy_id)
        self._failure_counts[strategy_id] = 0

    def is_active(self, strategy_id: str) -> bool:
        return strategy_id not in self._deactivated
