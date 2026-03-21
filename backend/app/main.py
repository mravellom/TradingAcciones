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

    logger.info(
        "trading_platform_started",
        execution_mode=settings.execution_mode,
        debug=settings.debug,
    )

    yield

    # Graceful Shutdown
    logger.info("shutting_down_trading_platform")

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
        version=settings.app_version,
        lifespan=lifespan,
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
