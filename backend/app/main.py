import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.api.websocket.routes import router as ws_router
from app.api.websocket.ws_manager import manager as ws_manager
from app.config import settings
from app.core.database import async_session_factory, engine
from app.core.exceptions import TradingPlatformError
from app.core.logging import get_logger, setup_logging
from app.core.redis import get_redis

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_logging()
    logger.info("starting_trading_platform", version=settings.app_version)

    # Verify DB connection
    async with engine.begin() as conn:
        await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    logger.info("database_connected")

    # Verify Redis connection
    redis = get_redis()
    await redis.ping()
    logger.info("redis_connected")

    # Connect executor BEFORE reconciliation (needed for LIVE mode reconciliation)
    live_executor = None
    if settings.execution_mode.upper() == "LIVE":
        try:
            from app.pipeline.execution.binance_executor import BinanceExecutor
            live_executor = BinanceExecutor()
            await live_executor.connect()
            logger.info("binance_executor_connected_for_reconciliation")
        except Exception as e:
            logger.error("binance_executor_connect_failed", error=str(e))
            # Continue without executor — reconciler will cancel orphaned orders

    # Run startup reconciliation WITH executor (before setting RUNNING)
    try:
        from app.tasks.startup_reconciler import reconcile
        async with async_session_factory() as session:
            await reconcile(session, executor=live_executor)
            await session.commit()
        logger.info("startup_reconciliation_completed")
    except Exception as e:
        logger.error("startup_reconciliation_failed", error=str(e))

    await redis.set("system:status", "RUNNING")

    # Initialize Alpaca for US stocks if enabled
    alpaca_client = None
    alpaca_ws = None
    alpaca_ws_task = None
    if settings.alpaca_enabled:
        try:
            from app.exchange.alpaca_client import AlpacaClient
            from app.exchange.alpaca_ws import AlpacaWebSocket

            alpaca_client = AlpacaClient()
            await alpaca_client.connect()
            logger.info("alpaca_client_connected")

            alpaca_ws = AlpacaWebSocket()
            for sym in settings.stock_symbols:
                await alpaca_ws.subscribe_ticker(sym)
            alpaca_ws_task = asyncio.create_task(alpaca_ws.start())
            logger.info("alpaca_ws_started", symbols=settings.stock_symbols)
        except Exception as e:
            logger.error("alpaca_startup_failed", error=str(e))
            alpaca_client = None
            alpaca_ws = None

    # Initialize Binance WebSocket for crypto price feeds
    binance_ws = None
    binance_ws_task = None
    try:
        from app.exchange.binance_ws import BinanceWebSocket

        binance_ws = BinanceWebSocket(testnet=settings.binance_testnet)
        crypto_symbols = ["BTCUSDT", "ETHUSDT"]
        for sym in crypto_symbols:
            await binance_ws.subscribe_ticker(sym)
        binance_ws_task = asyncio.create_task(binance_ws.start())
        logger.info("binance_ws_started", symbols=crypto_symbols)
    except Exception as e:
        logger.error("binance_ws_startup_failed", error=str(e))
        binance_ws = None

    # Store alpaca_client in app state for dependency injection
    app_instance = app  # type: ignore
    app_instance.state.alpaca_client = alpaca_client

    # Start runtime reconciler as background task (LIVE mode only)
    reconciler_task = None
    reconciler = None
    if live_executor is not None:
        try:
            from app.tasks.runtime_reconciler import RuntimeReconciler
            reconciler = RuntimeReconciler(
                executor=live_executor,
                session_factory=async_session_factory,
            )
            reconciler_task = asyncio.create_task(reconciler.start())
            logger.info("runtime_reconciler_launched")
        except Exception as e:
            logger.error("runtime_reconciler_launch_failed", error=str(e))

    # ── Background trading tasks (SignalScanner, PositionMonitor, DailyReset) ──
    background_tasks: list[asyncio.Task] = []
    scanner = None
    signal_executor = None
    position_monitor = None
    daily_reset = None
    exchange_client = None

    try:
        from decimal import Decimal

        from sqlalchemy import select

        from app.domain.enums import ExecutionMode
        from app.models.risk_config import RiskConfig
        from app.models.strategy_config import StrategyConfig
        from app.pipeline.strategy.momentum import MomentumStrategy
        from app.pipeline.strategy.stock_momentum import StockMomentumStrategy
        from app.services.market_data import MarketDataService
        from app.tasks.daily_reset import DailyResetTask
        from app.tasks.position_monitor import PositionMonitor
        from app.tasks.signal_scanner import SignalScanner

        # Load active risk profile
        risk_config = None
        async with async_session_factory() as session:
            stmt = select(RiskConfig).where(RiskConfig.is_active == True)
            result = await session.execute(stmt)
            risk_config = result.scalar_one_or_none()

        strategy_kwargs = {}
        if risk_config:
            strategy_kwargs = {
                "min_confidence": risk_config.min_confidence,
                "min_agreeing_signals": (
                    risk_config.min_agreeing_signals
                    if risk_config.allow_partial_signal_agreement
                    else None
                ),
                "use_atr_for_sl_tp": risk_config.use_atr_for_sl_tp,
                "atr_period": risk_config.atr_period,
                "atr_sl_multiplier": risk_config.atr_sl_multiplier,
                "atr_tp_multiplier": risk_config.atr_tp_multiplier,
            }
            logger.info(
                "risk_profile_loaded",
                profile=risk_config.profile_type,
                min_confidence=str(risk_config.min_confidence),
            )

        # Load active strategies from DB
        async with async_session_factory() as session:
            stmt = select(StrategyConfig).where(StrategyConfig.is_active == True)
            result = await session.execute(stmt)
            active_configs = list(result.scalars().all())

        # Build strategy instances
        strategies = []
        for cfg in active_configs:
            if cfg.strategy_type == "stock_momentum":
                s = StockMomentumStrategy(strategy_id=cfg.id, **strategy_kwargs)
                s.symbols = cfg.symbols or settings.stock_symbols
                strategies.append(s)
                logger.info("strategy_loaded", name=cfg.name, type=cfg.strategy_type, symbols=s.symbols)
            elif cfg.strategy_type == "momentum":
                s = MomentumStrategy(strategy_id=cfg.id, **strategy_kwargs)
                s.symbols = cfg.symbols or ["BTCUSDT", "ETHUSDT"]
                strategies.append(s)
                logger.info("strategy_loaded", name=cfg.name, type=cfg.strategy_type, symbols=s.symbols)

        # Build MarketDataService — needs at least one exchange
        exchange_client = None
        try:
            from app.exchange.binance_client import BinanceClient
            exchange_client = BinanceClient()
            await exchange_client.connect()
            logger.info("binance_client_connected")
        except Exception as e:
            logger.warning("binance_connect_skipped", error=str(e))

        market_data = MarketDataService(
            exchange=exchange_client or alpaca_client,
            stock_exchange=alpaca_client if exchange_client else None,
        )

        # 1. Signal Scanner
        if strategies:
            scanner = SignalScanner(
                strategies=strategies,
                market_data=market_data,
                session_factory=async_session_factory,
                scan_interval=60,
            )
            background_tasks.append(asyncio.create_task(scanner.start()))
            logger.info("signal_scanner_started", strategies=len(strategies), interval=60)

        # 2. Signal Executor (signal → risk → capital → execution → position)
        from app.pipeline.capital_manager.capital_manager import CapitalManager
        from app.pipeline.execution.guard import ExecutionGuard
        from app.pipeline.execution.paper_engine import PaperEngine
        from app.tasks.signal_executor import SignalExecutor

        paper_engine = PaperEngine()
        guard = ExecutionGuard(
            max_price_drift_pct=Decimal(str(settings.guard_max_price_drift_pct)),
            max_spread_pct=Decimal(str(settings.guard_max_spread_pct)),
            min_volume_24h=Decimal(str(settings.guard_min_volume_24h)),
            stock_max_price_drift_pct=Decimal(str(settings.guard_stock_max_price_drift_pct)),
            stock_max_spread_pct=Decimal(str(settings.guard_stock_max_spread_pct)),
            stock_min_volume_24h=Decimal(str(settings.guard_stock_min_volume_24h)),
        )

        signal_executor = SignalExecutor(
            executor=paper_engine,
            guard=guard,
            market_data=market_data,
            session_factory=async_session_factory,
        )
        background_tasks.append(asyncio.create_task(signal_executor.start()))
        logger.info("signal_executor_started")

        # 3. Position Monitor
        exec_mode = (
            ExecutionMode.LIVE
            if settings.execution_mode.upper() == "LIVE"
            else ExecutionMode.PAPER
        )
        position_monitor = PositionMonitor(
            session_factory=async_session_factory,
            execution_mode=exec_mode,
            check_interval=5,
        )
        background_tasks.append(asyncio.create_task(position_monitor.start()))
        logger.info("position_monitor_started", interval=5)

        # 4. Daily Reset
        daily_reset = DailyResetTask(session_factory=async_session_factory)
        background_tasks.append(asyncio.create_task(daily_reset.start()))
        logger.info("daily_reset_started")

    except Exception as e:
        logger.error("background_tasks_init_failed", error=str(e))

    logger.info(
        "trading_platform_started",
        execution_mode=settings.execution_mode,
        debug=settings.debug,
        background_tasks=len(background_tasks),
    )

    yield

    # Graceful Shutdown
    logger.info("shutting_down_trading_platform")

    # Stop background trading tasks
    if scanner:
        await scanner.stop()
    if signal_executor:
        await signal_executor.stop()
    if position_monitor:
        await position_monitor.stop()
    if daily_reset:
        await daily_reset.stop()
    for t in background_tasks:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    if background_tasks:
        logger.info("background_tasks_stopped", count=len(background_tasks))

    # Stop Binance WebSocket
    if binance_ws_task is not None and binance_ws is not None:
        try:
            await binance_ws.stop()
            binance_ws_task.cancel()
            try:
                await binance_ws_task
            except asyncio.CancelledError:
                pass
            logger.info("binance_ws_stopped")
        except Exception:
            pass

    # Stop Alpaca WebSocket
    if alpaca_ws_task is not None and alpaca_ws is not None:
        try:
            await alpaca_ws.stop()
            alpaca_ws_task.cancel()
            try:
                await alpaca_ws_task
            except asyncio.CancelledError:
                pass
            logger.info("alpaca_ws_stopped")
        except Exception:
            pass
    if alpaca_client is not None:
        try:
            await alpaca_client.disconnect()
        except Exception:
            pass

    # Disconnect Binance if connected
    if exchange_client is not None:
        try:
            await exchange_client.disconnect()
        except Exception:
            pass

    # Stop runtime reconciler
    if reconciler_task is not None and reconciler is not None:
        try:
            await reconciler.stop()
            reconciler_task.cancel()
            try:
                await reconciler_task
            except asyncio.CancelledError:
                pass
            logger.info("runtime_reconciler_stopped")
        except Exception:
            pass

    # 1. Mark system as shutting down
    try:
        await redis.set("system:status", "SHUTTING_DOWN")
    except Exception:
        pass

    # 2. Close WebSocket connections
    try:
        await ws_manager.shutdown()
        logger.info("websocket_connections_closed")
    except Exception as e:
        logger.error("websocket_shutdown_error", error=str(e))

    # 3. Close DB and Redis
    await engine.dispose()
    try:
        await redis.aclose()
    except Exception:
        pass

    logger.info("trading_platform_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="Crypto trading platform with ML signals, risk management, and paper/live execution.",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    # CORS — configurable via settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    # Global exception handler for domain errors
    @app.exception_handler(TradingPlatformError)
    async def trading_error_handler(request: Request, exc: TradingPlatformError):
        return JSONResponse(
            status_code=400,
            content={
                "error": exc.code or "TRADING_ERROR",
                "message": exc.message,
            },
        )

    # Global unhandled exception handler
    @app.exception_handler(Exception)
    async def global_error_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
        )

    app.include_router(api_v1_router)
    app.include_router(ws_router)

    return app


app = create_app()
