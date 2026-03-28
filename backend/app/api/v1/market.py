from fastapi import APIRouter, Query

from app.exchange.binance_client import BinanceClient

router = APIRouter(prefix="/market", tags=["market"])

# Shared client instance (initialized on first use)
_binance: BinanceClient | None = None


async def _get_binance() -> BinanceClient:
    global _binance
    if _binance is None:
        _binance = BinanceClient()
        await _binance.connect()
    return _binance


@router.get("/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Get current ticker data (price, bid, ask, volume) for a symbol."""
    binance = await _get_binance()
    ticker = await binance.get_ticker(symbol.upper())
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
    interval: str = Query(default="1h", pattern="^(1m|5m|15m|30m|1h|4h|1d)$"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get candlestick/kline data for a symbol with configurable interval and limit."""
    binance = await _get_binance()
    klines = await binance.get_klines(symbol.upper(), interval, limit)
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
