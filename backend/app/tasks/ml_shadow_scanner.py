"""ML Shadow Scanner — generates ML signals without executing.

Runs every scan interval:
1. Fetches latest klines from Binance (or cache)
2. Runs MLSignalGenerator for each symbol
3. Saves shadow signals to DB with shadow_mode=True
4. Tracks what WOULD have happened (simulated PnL)

After 2+ weeks of shadow data, compare ML vs baseline in analytics.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import EventPublisher
from app.core.logging import get_logger
from app.domain.enums import AggregateType, EventType
from app.exchange.base import ExchangeClient, Kline
from app.ml.serving.ml_signal_generator import MLSignalGenerator
from app.models.signal import Signal as SignalModel
from app.repositories.event_repo import EventRepository

logger = get_logger(__name__)

DEFAULT_SCAN_INTERVAL = 3600  # 1 hour (matches 1h timeframe)
KLINE_FETCH_LIMIT = 100       # Last 100 candles for feature computation


class MLShadowScanner:
    """Background task: ML signal generation in shadow mode."""

    def __init__(
        self,
        symbols: list[str],
        exchange: ExchangeClient,
        session_factory,
        strategy_id: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ):
        self._symbols = symbols
        self._exchange = exchange
        self._session_factory = session_factory
        self._strategy_id = strategy_id
        self._scan_interval = scan_interval
        self._running = False
        self._publisher = EventPublisher()

        # Create ML generators (shadow mode)
        self._generators: dict[str, MLSignalGenerator] = {}
        for sym in symbols:
            gen = MLSignalGenerator(sym, shadow_mode=True)
            if gen._loaded:
                self._generators[sym] = gen
                logger.info("ml_shadow_generator_loaded", symbol=sym)
            else:
                logger.warning("ml_shadow_generator_skipped", symbol=sym)

    async def start(self) -> None:
        self._running = True
        logger.info(
            "ml_shadow_scanner_started",
            symbols=list(self._generators.keys()),
            interval=self._scan_interval,
        )
        while self._running:
            try:
                await self._scan_cycle()
            except Exception as e:
                logger.error("ml_shadow_scan_error", error=str(e))
            await asyncio.sleep(self._scan_interval)

    async def stop(self) -> None:
        self._running = False
        logger.info("ml_shadow_scanner_stopped")

    async def _scan_cycle(self) -> None:
        """One scan: check all symbols for ML signals."""
        for symbol, generator in self._generators.items():
            try:
                await self._scan_symbol(symbol, generator)
            except Exception as e:
                logger.error("ml_shadow_symbol_error", symbol=symbol, error=str(e))

    async def _scan_symbol(self, symbol: str, generator: MLSignalGenerator) -> None:
        """Fetch klines and generate ML signal for one symbol."""
        # Fetch latest klines
        klines = await self._exchange.get_klines(symbol, "1h", KLINE_FETCH_LIMIT)
        if len(klines) < 60:
            return

        # Generate signal
        signal = await generator.generate(symbol, klines)

        if signal is None:
            logger.debug("ml_shadow_no_signal", symbol=symbol)
            return

        # Validate SL/TP before saving
        if signal.entry_price <= 0 or signal.stop_loss <= 0 or signal.take_profit <= 0:
            logger.warning("ml_shadow_invalid_prices", symbol=symbol)
            return
        if signal.stop_loss >= signal.entry_price:
            logger.warning("ml_shadow_invalid_sl", symbol=symbol, sl=str(signal.stop_loss), entry=str(signal.entry_price))
            return
        if signal.take_profit <= signal.entry_price:
            logger.warning("ml_shadow_invalid_tp", symbol=symbol, tp=str(signal.take_profit), entry=str(signal.entry_price))
            return

        # Save shadow signal to DB
        async with self._session_factory() as session:
            db_signal = SignalModel(
                symbol=symbol,
                signal_type=signal.signal_type.value,
                confidence=signal.confidence,
                timeframe="1h",
                indicators={
                    **signal.indicators,
                    "source": "ml_shadow",
                },
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                strategy_id=uuid4(),  # Shadow doesn't link to real strategy
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
            session.add(db_signal)

            # Event
            event_repo = EventRepository(session)
            await event_repo.append(
                aggregate_type=AggregateType.SIGNAL,
                aggregate_id=db_signal.id,
                event_type=EventType.SIGNAL_GENERATED,
                event_data={
                    "symbol": symbol,
                    "signal_type": signal.signal_type.value,
                    "confidence": str(signal.confidence),
                    "ml_probability": signal.indicators.get("ml_probability", 0),
                    "source": "ml_shadow",
                    "entry_price": str(signal.entry_price),
                    "stop_loss": str(signal.stop_loss),
                    "take_profit": str(signal.take_profit),
                },
            )

            await session.commit()

        logger.info(
            "ml_shadow_signal_generated",
            symbol=symbol,
            confidence=str(signal.confidence),
            probability=signal.indicators.get("ml_probability", 0),
            entry=str(signal.entry_price),
        )

        # Publish for dashboard (real-time)
        await self._publisher.signal_generated({
            "symbol": symbol,
            "signal_type": signal.signal_type.value,
            "confidence": str(signal.confidence),
            "source": "ml_shadow",
            "ml_probability": signal.indicators.get("ml_probability", 0),
        })
