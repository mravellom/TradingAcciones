from fastapi import APIRouter, Query

from app.config import settings
from app.exchange.base import ExchangeClient
from app.exchange.binance_client import BinanceClient

router = APIRouter(prefix="/market", tags=["market"])

# Shared client instances (initialized on first use)
_binance: BinanceClient | None = None
_alpaca: ExchangeClient | None = None


async def _get_binance() -> BinanceClient:
    global _binance
    if _binance is None:
        _binance = BinanceClient()
        await _binance.connect()
    return _binance


async def _get_exchange(symbol: str) -> ExchangeClient:
    """Route to correct exchange based on symbol."""
    if settings.alpaca_enabled and symbol.upper() in settings.stock_symbols:
        global _alpaca
        if _alpaca is None:
            from app.exchange.alpaca_client import AlpacaClient
            _alpaca = AlpacaClient()
            await _alpaca.connect()
        return _alpaca
    return await _get_binance()


@router.get("/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Get current ticker data (price, bid, ask, volume) for a symbol."""
    exchange = await _get_exchange(symbol)
    ticker = await exchange.get_ticker(symbol.upper())
    return {
        "symbol": ticker.symbol,
        "price": str(ticker.price),
        "bid": str(ticker.bid),
        "ask": str(ticker.ask),
        "volume_24h": str(ticker.volume_24h),
        "timestamp": ticker.timestamp.isoformat(),
    }


@router.get("/klines/{symbol}")
async def get_klines(
    symbol: str,
    interval: str = Query(default="1h", pattern="^(1m|5m|15m|30m|1h|4h|1d|1w)$"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get candlestick/kline data for a symbol with configurable interval and limit."""
    exchange = await _get_exchange(symbol)
    klines = await exchange.get_klines(symbol.upper(), interval, limit)
    return [
        {
            "open_time": k.open_time.isoformat(),
            "open": str(k.open),
            "high": str(k.high),
            "low": str(k.low),
            "close": str(k.close),
            "volume": str(k.volume),
            "close_time": k.close_time.isoformat(),
        }
        for k in klines
    ]
