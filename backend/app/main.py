from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.api.websocket.routes import router as ws_router
from app.api.websocket.ws_manager import manager as ws_manager
from app.config import settings
from app.core.database import engine
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
    await redis.set("system:status", "RUNNING")
    logger.info("redis_connected")

    logger.info(
        "trading_platform_started",
        execution_mode=settings.execution_mode,
        debug=settings.debug,
    )

    yield

    # Graceful Shutdown
    logger.info("shutting_down_trading_platform")

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

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:4200"],
        allow_credentials=True,
        allow_methods=["*"],
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
