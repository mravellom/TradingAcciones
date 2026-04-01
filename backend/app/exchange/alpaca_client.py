"""Alpaca exchange client for US stocks (S&P 500, NASDAQ)."""

import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestQuoteRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient

from app.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.exchange.base import ExchangeClient, Kline, SymbolInfo, Ticker

logger = get_logger(__name__)

TICKER_CACHE_TTL = 5
KLINES_CACHE_TTL = 30
EXCHANGE_INFO_CACHE_TTL = 3600

_INTERVAL_MAP = {
    "1m": TimeFrame(1, TimeFrameUnit.Minute),
    "5m": TimeFrame(5, TimeFrameUnit.Minute),
    "15m": TimeFrame(15, TimeFrameUnit.Minute),
    "1h": TimeFrame(1, TimeFrameUnit.Hour),
    "4h": TimeFrame(4, TimeFrameUnit.Hour),
    "1d": TimeFrame(1, TimeFrameUnit.Day),
    "1w": TimeFrame(1, TimeFrameUnit.Week),
}

# Approximate bar durations for calculating start date from limit
_INTERVAL_DURATION = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
}


class AlpacaClient(ExchangeClient):
    """Alpaca exchange client for US stock market data and trading."""

    def __init__(self):
        self._data_client: StockHistoricalDataClient | None = None
        self._trading_client: TradingClient | None = None
        self._redis = get_redis()

    @property
    def asset_class(self) -> str:
        return "STOCKS"

    @property
    def data_client(self) -> StockHistoricalDataClient:
        if self._data_client is None:
            raise RuntimeError("AlpacaClient not connected. Call connect() first.")
        return self._data_client

    @property
    def trading_client(self) -> TradingClient:
        if self._trading_client is None:
            raise RuntimeError("AlpacaClient not connected. Call connect() first.")
        return self._trading_client

    async def connect(self) -> None:
        if self._data_client is not None:
            return
        self._data_client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_api_secret,
        )
        self._trading_client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_api_secret,
            paper=True,
        )
        # Verify credentials
        account = self._trading_client.get_account()
        logger.info(
            "alpaca_client_connected",
            account_status=account.status,
            buying_power=str(account.buying_power),
        )

    async def disconnect(self) -> None:
        self._data_client = None
        self._trading_client = None
        logger.info("alpaca_client_disconnected")

    async def ping(self) -> float:
        start = time.monotonic()
        self.trading_client.get_clock()
        latency_ms = (time.monotonic() - start) * 1000
        return round(latency_ms, 2)

    async def get_ticker(self, symbol: str) -> Ticker:
        cache_key = f"ticker:{symbol}"
        cached = await self._redis.hgetall(cache_key)
        if cached:
            return Ticker(
                symbol=symbol,
                price=Decimal(cached["price"]),
                bid=Decimal(cached["bid"]),
                ask=Decimal(cached["ask"]),
                volume_24h=Decimal(cached["volume_24h"]),
                timestamp=datetime.fromisoformat(cached["timestamp"]),
            )

        request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = self.data_client.get_stock_latest_quote(request)
        quote = quotes[symbol]
        now = datetime.now(timezone.utc)

        # Use midpoint as price
        bid = Decimal(str(quote.bid_price))
        ask = Decimal(str(quote.ask_price))
        price = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)

        ticker = Ticker(
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            volume_24h=Decimal(str(quote.bid_size + quote.ask_size)),
            timestamp=now,
        )

        await self._redis.hset(cache_key, mapping={
            "price": str(ticker.price),
            "bid": str(ticker.bid),
            "ask": str(ticker.ask),
            "volume_24h": str(ticker.volume_24h),
            "timestamp": now.isoformat(),
        })
        await self._redis.expire(cache_key, TICKER_CACHE_TTL)

        return ticker

    async def get_klines(
        self, symbol: str, interval: str, limit: int = 100
    ) -> list[Kline]:
        cache_key = f"klines:{symbol}:{interval}:{limit}"
        cached = await self._redis.get(cache_key)
        if cached:
            raw_list = json.loads(cached)
            return [self._parse_cached_kline(k) for k in raw_list]

        timeframe = _INTERVAL_MAP.get(interval)
        if timeframe is None:
            raise ValueError(f"Unsupported interval: {interval}")

        # Calculate start date based on limit and interval
        duration = _INTERVAL_DURATION[interval]
        # Add extra buffer for weekends/holidays
        buffer_factor = 2.0 if interval in ("1d", "1w") else 1.5
        start = datetime.now(timezone.utc) - (duration * int(limit * buffer_factor))

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe,
            start=start,
            limit=limit,
        )
        bars_response = self.data_client.get_stock_bars(request)
        bars = bars_response[symbol] if symbol in bars_response else []

        klines = []
        for bar in bars:
            klines.append(Kline(
                symbol=symbol,
                interval=interval,
                open_time=bar.timestamp,
                open=Decimal(str(bar.open)),
                high=Decimal(str(bar.high)),
                low=Decimal(str(bar.low)),
                close=Decimal(str(bar.close)),
                volume=Decimal(str(bar.volume)),
                close_time=bar.timestamp + duration,
            ))

        # Cache serialized
        serializable = [
            {
                "symbol": k.symbol,
                "interval": k.interval,
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
        await self._redis.set(cache_key, json.dumps(serializable), ex=KLINES_CACHE_TTL)

        return klines

    async def get_exchange_info(self, symbol: str) -> SymbolInfo:
        cache_key = f"exchange_info:{symbol}"
        cached = await self._redis.hgetall(cache_key)
        if cached:
            return SymbolInfo(
                symbol=symbol,
                base_asset=cached["base_asset"],
                quote_asset=cached["quote_asset"],
                min_qty=Decimal(cached["min_qty"]),
                max_qty=Decimal(cached["max_qty"]),
                step_size=Decimal(cached["step_size"]),
                min_notional=Decimal(cached["min_notional"]),
                tick_size=Decimal(cached["tick_size"]),
                asset_class="STOCKS",
            )

        asset = self.trading_client.get_asset(symbol)

        result = SymbolInfo(
            symbol=symbol,
            base_asset=symbol,
            quote_asset="USD",
            min_qty=Decimal("1"),
            max_qty=Decimal("99999999"),
            step_size=Decimal("1"),
            min_notional=Decimal("1"),
            tick_size=Decimal("0.01"),
            asset_class="STOCKS",
        )

        # Check if fractional shares are supported
        if getattr(asset, "fractionable", False):
            result = SymbolInfo(
                symbol=symbol,
                base_asset=symbol,
                quote_asset="USD",
                min_qty=Decimal("0.001"),
                max_qty=Decimal("99999999"),
                step_size=Decimal("0.001"),
                min_notional=Decimal("1"),
                tick_size=Decimal("0.01"),
                asset_class="STOCKS",
            )

        await self._redis.hset(cache_key, mapping={
            "base_asset": result.base_asset,
            "quote_asset": result.quote_asset,
            "min_qty": str(result.min_qty),
            "max_qty": str(result.max_qty),
            "step_size": str(result.step_size),
            "min_notional": str(result.min_notional),
            "tick_size": str(result.tick_size),
        })
        await self._redis.expire(cache_key, EXCHANGE_INFO_CACHE_TTL)

        return result

    async def get_all_tickers(self) -> list[Ticker]:
        symbols = settings.stock_symbols
        request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
        quotes = self.data_client.get_stock_latest_quote(request)
        now = datetime.now(timezone.utc)

        tickers = []
        for sym, quote in quotes.items():
            bid = Decimal(str(quote.bid_price))
            ask = Decimal(str(quote.ask_price))
            price = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)
            tickers.append(Ticker(
                symbol=sym,
                price=price,
                bid=bid,
                ask=ask,
                volume_24h=Decimal(str(quote.bid_size + quote.ask_size)),
                timestamp=now,
            ))
        return tickers

    @staticmethod
    def _parse_cached_kline(data: dict) -> Kline:
        return Kline(
            symbol=data["symbol"],
            interval=data["interval"],
            open_time=datetime.fromisoformat(data["open_time"]),
            open=Decimal(data["open"]),
            high=Decimal(data["high"]),
            low=Decimal(data["low"]),
            close=Decimal(data["close"]),
            volume=Decimal(data["volume"]),
            close_time=datetime.fromisoformat(data["close_time"]),
        )
