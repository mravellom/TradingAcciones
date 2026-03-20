from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.market import router as market_router
from app.api.v1.orders import router as orders_router
from app.api.v1.portfolio import router as portfolio_router
from app.api.v1.positions import router as positions_router
from app.api.v1.risk import router as risk_router
from app.api.v1.signals import router as signals_router
from app.api.v1.strategies import router as strategies_router
from app.api.v1.system import router as system_router
from app.api.v1.trades import router as trades_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(system_router)
api_v1_router.include_router(market_router)
api_v1_router.include_router(signals_router)
api_v1_router.include_router(orders_router)
api_v1_router.include_router(positions_router)
api_v1_router.include_router(trades_router)
api_v1_router.include_router(portfolio_router)
api_v1_router.include_router(risk_router)
api_v1_router.include_router(strategies_router)
api_v1_router.include_router(analytics_router)
