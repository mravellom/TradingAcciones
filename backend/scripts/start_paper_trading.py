"""Start paper trading with all background tasks.

Launches:
1. FastAPI server (API + WebSocket)
2. Signal Scanner (RSI + SMA every 60s)
3. ML Shadow Scanner (XGBoost every 1h)
4. Position Monitor (SL/TP check every 2s)
5. Daily Reset (daily PnL reset at midnight UTC)

Usage:
    python -m scripts.start_paper_trading
"""
import asyncio
import signal
import sys
from decimal import Decimal

import uvicorn

from app.config import settings
from app.core.database import async_session_factory
from app.core.logging import get_logger, setup_logging
from app.domain.enums import ExecutionMode
from app.exchange.binance_client import BinanceClient
from app.ml.serving.ml_signal_generator import MLSignalGenerator
from app.models.risk_config import RiskConfig
from app.pipeline.capital_manager.capital_manager import CapitalManager
from app.pipeline.execution.guard import ExecutionGuard
from app.pipeline.execution.paper_engine import PaperEngine
from app.pipeline.risk_manager.risk_manager import RiskManager
from app.pipeline.signal_engine.composite import CompositeSignalGenerator
from app.pipeline.signal_engine.rsi import RSISignalGenerator
from app.pipeline.signal_engine.sma_crossover import SMACrossoverSignalGenerator
from app.pipeline.strategy.momentum import MomentumStrategy
from app.pipeline.strategy.stock_momentum import StockMomentumStrategy
from app.services.market_data import MarketDataService
from app.tasks.daily_reset import DailyResetTask
from app.tasks.position_monitor import PositionMonitor
from app.tasks.signal_scanner import SignalScanner

setup_logging()
logger = get_logger(__name__)


async def _load_risk_profile() -> RiskConfig | None:
    """Load the active risk config from DB."""
    from sqlalchemy import select
    async with async_session_factory() as session:
        stmt = select(RiskConfig).where(RiskConfig.is_active == True)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


def _create_ml_strategy(strategy_id, symbols, risk_config: RiskConfig | None = None):
    """Create ML composite strategy. Falls back to None if models missing."""
    from app.pipeline.strategy.ml_composite import MLCompositeStrategy

    # Extract profile params
    kwargs = {}
    if risk_config:
        kwargs = {
            "min_confidence": risk_config.min_confidence,
            "min_agreeing_signals": risk_config.min_agreeing_signals if risk_config.allow_partial_signal_agreement else None,
            "use_atr_for_sl_tp": risk_config.use_atr_for_sl_tp,
            "atr_period": risk_config.atr_period,
            "atr_sl_multiplier": risk_config.atr_sl_multiplier,
            "atr_tp_multiplier": risk_config.atr_tp_multiplier,
        }

    # Create one strategy per symbol that has a trained model
    strategies = []
    for sym in symbols:
        try:
            s = MLCompositeStrategy(strategy_id=strategy_id, symbol=sym, **kwargs)
            strategies.append(s)
            logger.info("ml_composite_loaded", symbol=sym, weights="ML=0.6 RSI=0.2 SMA=0.2")
        except ValueError:
            logger.warning("ml_composite_skipped", symbol=sym, reason="no model")

    if not strategies:
        logger.warning("ml_composite_none_loaded", fallback="momentum_only")
        return None

    # Return first strategy (signal scanner runs all)
    # Actually we need to return all — but SignalScanner takes a list
    return strategies


async def start_background_tasks():
    """Start all background tasks."""
    logger.info("starting_background_tasks")

    # Load active risk profile
    risk_config = await _load_risk_profile()
    if risk_config:
        logger.info(
            "risk_profile_loaded",
            profile=risk_config.profile_type,
            min_confidence=str(risk_config.min_confidence),
            max_positions=risk_config.max_positions,
            partial_agreement=risk_config.allow_partial_signal_agreement,
            use_atr=risk_config.use_atr_for_sl_tp,
        )
    else:
        logger.warning("no_risk_config_found_using_defaults")

    # Profile-aware strategy kwargs
    strategy_kwargs = {}
    if risk_config:
        strategy_kwargs = {
            "min_confidence": risk_config.min_confidence,
            "min_agreeing_signals": risk_config.min_agreeing_signals if risk_config.allow_partial_signal_agreement else None,
            "use_atr_for_sl_tp": risk_config.use_atr_for_sl_tp,
            "atr_period": risk_config.atr_period,
            "atr_sl_multiplier": risk_config.atr_sl_multiplier,
            "atr_tp_multiplier": risk_config.atr_tp_multiplier,
        }

    # Exchange client
    exchange = BinanceClient()
    try:
        await exchange.connect()
    except Exception as e:
        logger.error("binance_connect_failed", error=str(e))
        logger.info("running_without_binance_connection")
        exchange = None

    # Get strategy ID from DB
    from sqlalchemy import select
    from app.models.strategy_config import StrategyConfig

    async with async_session_factory() as session:
        stmt = select(StrategyConfig).where(StrategyConfig.is_active == True)
        result = await session.execute(stmt)
        active_strategies = list(result.scalars().all())

    if not active_strategies:
        logger.error("no_active_strategy")
        return

    # Use first crypto strategy as primary
    strategy = active_strategies[0]
    strategy_id = strategy.id
    symbols = strategy.symbols or ["BTCUSDT", "ETHUSDT"]
    for s in active_strategies:
        logger.info("active_strategy", name=s.name, asset_class=s.asset_class, symbols=s.symbols)

    tasks = []

    # 1. Signal Scanner (ML + RSI + SMA composite)
    # Initialize Alpaca exchange if enabled
    alpaca_exchange = None
    if settings.alpaca_enabled:
        try:
            from app.exchange.alpaca_client import AlpacaClient
            alpaca_exchange = AlpacaClient()
            await alpaca_exchange.connect()
            logger.info("alpaca_client_connected_for_paper_trading")
        except Exception as e:
            logger.error("alpaca_connect_failed", error=str(e))
            alpaca_exchange = None

    if exchange:
        market_data = MarketDataService(exchange, stock_exchange=alpaca_exchange)

        # Create ML-enhanced strategies (one per symbol)
        ml_strategies = _create_ml_strategy(strategy_id, symbols, risk_config)
        if ml_strategies:
            strategies = ml_strategies
        else:
            strategies = [MomentumStrategy(strategy_id=strategy_id, **strategy_kwargs)]

        # Add stock strategy if Alpaca is enabled
        if alpaca_exchange:
            from uuid import uuid4
            stock_strategy = StockMomentumStrategy(strategy_id=uuid4(), **strategy_kwargs)
            stock_strategy.symbols = settings.stock_symbols
            strategies.append(stock_strategy)
            logger.info("stock_momentum_strategy_added", symbols=settings.stock_symbols)

        scanner = SignalScanner(
            strategies=strategies,
            market_data=market_data,
            session_factory=async_session_factory,
            scan_interval=60,
        )
        tasks.append(asyncio.create_task(scanner.start()))
        logger.info(
            "signal_scanner_queued",
            interval=60,
            strategy_type="ml_composite" if ml_strategies else "momentum_only",
            stock_enabled=alpaca_exchange is not None,
        )

    # 2. Position Monitor
    monitor = PositionMonitor(
        session_factory=async_session_factory,
        execution_mode=ExecutionMode.PAPER,
        check_interval=5,
    )
    tasks.append(asyncio.create_task(monitor.start()))
    logger.info("position_monitor_queued", interval=5)

    # 3. Daily Reset
    daily_reset = DailyResetTask(session_factory=async_session_factory)
    tasks.append(asyncio.create_task(daily_reset.start()))
    logger.info("daily_reset_queued")

    # 4. ML Shadow Scanner (if models exist)
    if exchange:
        from app.tasks.ml_shadow_scanner import MLShadowScanner
        # Include stock symbols if Alpaca is enabled
        shadow_symbols = list(symbols)
        if alpaca_exchange and settings.alpaca_enabled:
            shadow_symbols.extend(settings.stock_symbols)
        shadow = MLShadowScanner(
            symbols=shadow_symbols,
            exchange=exchange,
            session_factory=async_session_factory,
            strategy_id=str(strategy_id),
            scan_interval=3600,  # Every 1h
        )
        if shadow._generators:
            tasks.append(asyncio.create_task(shadow.start()))
            logger.info("ml_shadow_scanner_queued", symbols=list(shadow._generators.keys()), interval=3600)
        else:
            logger.info("ml_shadow_scanner_skipped_no_models")

    logger.info("background_tasks_started", count=len(tasks))

    # Handle shutdown
    stop_event = asyncio.Event()

    def handle_signal(*_):
        logger.info("shutdown_signal_received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, handle_signal)

    await stop_event.wait()

    # Cancel all tasks
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    if exchange:
        await exchange.disconnect()
    if alpaca_exchange:
        await alpaca_exchange.disconnect()

    logger.info("background_tasks_stopped")


def main():
    print("=" * 60)
    print("  PAPER TRADING — Starting")
    print(f"  Mode: {settings.execution_mode}")
    print(f"  API: http://localhost:8000")
    print(f"  Docs: http://localhost:8000/docs")
    print(f"  Dashboard: http://localhost:4200")
    print("=" * 60)
    print()

    # Run background tasks (FastAPI is already running via run.py)
    asyncio.run(start_background_tasks())


if __name__ == "__main__":
    main()
