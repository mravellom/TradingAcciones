import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.domain.enums import AggregateType, AssetClass, EventType, SignalType
from app.exchange.base import ExchangeClient
from app.exchange.market_hours import is_us_market_open
from app.models.signal import Signal as SignalModel
from app.pipeline.strategy.base import Strategy
from app.pipeline.strategy.runner import StrategyRunner
from app.repositories.event_repo import EventRepository
from app.services.market_data import MarketDataService

logger = get_logger(__name__)

# Scan interval
DEFAULT_SCAN_INTERVAL = 60  # seconds


class SignalScanner:
    """Background task that periodically evaluates all active strategies.

    For each active strategy:
    1. Fetch klines for each symbol
    2. Run strategy evaluation
    3. Save generated signals to DB
    4. Emit SignalGenerated events
    """

    def __init__(
        self,
        strategies: list[Strategy],
        market_data: MarketDataService,
        session_factory,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ):
        self._runner = StrategyRunner()
        self._strategies = strategies
        self._market_data = market_data
        self._session_factory = session_factory
        self._scan_interval = scan_interval
        self._running = False

    async def start(self) -> None:
        """Start the periodic scan loop."""
        self._running = True
        logger.info("signal_scanner_started", interval=self._scan_interval)

        while self._running:
            try:
                await self._scan_cycle()
            except Exception as e:
                logger.error("signal_scanner_error", error=str(e))
            await asyncio.sleep(self._scan_interval)

    async def stop(self) -> None:
        self._running = False
        logger.info("signal_scanner_stopped")

    async def _scan_cycle(self) -> None:
        """One scan cycle: evaluate all strategies for all symbols."""
        # Collect unique symbols from all strategies
        symbols: set[str] = set()
        strategy_symbols: dict[UUID, list[str]] = {}

        for strategy in self._strategies:
            # In production, symbols come from StrategyConfig in DB
            # For now, we'll use a default set
            s_symbols = getattr(strategy, "symbols", ["BTCUSDT", "ETHUSDT"])
            strategy_symbols[strategy.id] = s_symbols
            symbols.update(s_symbols)

        # Add stock symbols if Alpaca is enabled and market is open
        if settings.alpaca_enabled and is_us_market_open():
            symbols.update(settings.stock_symbols)

        for symbol in symbols:
            await self._scan_symbol(symbol)

    async def _scan_symbol(self, symbol: str) -> None:
        """Evaluate all strategies for a single symbol."""
        # Determine timeframes needed
        timeframes = set()
        for strategy in self._strategies:
            timeframe = getattr(strategy, "timeframe", "1h")
            timeframes.add(timeframe)

        for timeframe in timeframes:
            try:
                klines = await self._market_data.get_klines(
                    symbol, timeframe, limit=100
                )

                intents = await self._runner.run_all(
                    self._strategies, symbol, klines, timeframe
                )

                for intent in intents:
                    if intent.action != SignalType.HOLD:
                        await self._save_signal(intent, timeframe)

            except Exception as e:
                logger.error(
                    "scan_symbol_error",
                    symbol=symbol,
                    timeframe=timeframe,
                    error=str(e),
                )

    async def _save_signal(self, intent, timeframe: str) -> None:
        """Persist signal to DB and emit event."""
        async with self._session_factory() as session:
            asset_class = (
                AssetClass.STOCKS.value
                if intent.symbol in settings.stock_symbols
                else AssetClass.CRYPTO.value
            )
            signal = SignalModel(
                symbol=intent.symbol,
                asset_class=asset_class,
                signal_type=intent.action.value,
                confidence=intent.confidence,
                timeframe=timeframe,
                indicators=intent.indicators,
                entry_price=intent.entry_price,
                stop_loss=intent.stop_loss,
                take_profit=intent.take_profit,
                strategy_id=intent.strategy_id,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            session.add(signal)

            # Event sourcing
            event_repo = EventRepository(session)
            await event_repo.append(
                aggregate_type=AggregateType.SIGNAL,
                aggregate_id=signal.id,
                event_type=EventType.SIGNAL_GENERATED,
                event_data={
                    "symbol": intent.symbol,
                    "signal_type": intent.action.value,
                    "confidence": str(intent.confidence),
                    "entry_price": str(intent.entry_price),
                    "stop_loss": str(intent.stop_loss),
                    "take_profit": str(intent.take_profit),
                    "indicators": intent.indicators,
                    "strategy_id": str(intent.strategy_id),
                },
            )

            await session.commit()

            logger.info(
                "signal_generated",
                symbol=intent.symbol,
                type=intent.action.value,
                confidence=str(intent.confidence),
                strategy_id=str(intent.strategy_id),
            )
