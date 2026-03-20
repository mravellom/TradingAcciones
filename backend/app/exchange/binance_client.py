import time
from datetime import datetime, timezone
from decimal import Decimal

from binance import AsyncClient

from app.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.exchange.base import ExchangeClient, Kline, SymbolInfo, Ticker

logger = get_logger(__name__)

# Cache TTLs in seconds
TICKER_CACHE_TTL = 5
KLINES_CACHE_TTL = 30
EXCHANGE_INFO_CACHE_TTL = 3600  # 1 hour


class BinanceClient(ExchangeClient):
    def __init__(self):
        self._client: AsyncClient | None = None
        self._redis = get_redis()

    async def connect(self) -> None:
        if self._client is not None:
            return
        self._client = await AsyncClient.create(
            api_key=settings.binance_api_key or None,
            api_secret=settings.binance_api_secret or None,
            testnet=settings.binance_testnet,
        )
        logger.info("binance_client_connected", testnet=settings.binance_testnet)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close_connection()
            self._client = None
            logger.info("binance_client_disconnected")

    @property
    def client(self) -> AsyncClient:
        if self._client is None:
            raise RuntimeError("BinanceClient not connected. Call connect() first.")
        return self._client

    async def ping(self) -> float:
        start = time.monotonic()
        await self.client.ping()
        latency_ms = (time.monotonic() - start) * 1000
        return round(latency_ms, 2)

    async def get_ticker(self, symbol: str) -> Ticker:
        # Check cache
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

        # Fetch from Binance
        ticker_data = await self.client.get_ticker(symbol=symbol)
        now = datetime.now(timezone.utc)

        ticker = Ticker(
            symbol=symbol,
            price=Decimal(ticker_data["lastPrice"]),
            bid=Decimal(ticker_data["bidPrice"]),
            ask=Decimal(ticker_data["askPrice"]),
            volume_24h=Decimal(ticker_data["quoteVolume"]),
            timestamp=now,
        )

        # Cache
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
        # Check cache
        cache_key = f"klines:{symbol}:{interval}:{limit}"
        cached = await self._redis.get(cache_key)
        if cached:
            import json
            raw_list = json.loads(cached)
            return [self._parse_kline(symbol, interval, k) for k in raw_list]

        # Fetch from Binance
        raw_klines = await self.client.get_klines(
            symbol=symbol, interval=interval, limit=limit
        )

        klines = [self._parse_kline(symbol, interval, k) for k in raw_klines]

        # Cache raw data
        import json
        await self._redis.set(
            cache_key, json.dumps(raw_klines), ex=KLINES_CACHE_TTL
        )

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
            )

        info = await self.client.get_exchange_info()
        symbol_info = None
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                symbol_info = s
                break

        if symbol_info is None:
            raise ValueError(f"Symbol {symbol} not found on Binance")

        # Parse filters
        lot_size = self._get_filter(symbol_info, "LOT_SIZE")
        min_notional_filter = self._get_filter(symbol_info, "NOTIONAL") or self._get_filter(
            symbol_info, "MIN_NOTIONAL"
        )
        price_filter = self._get_filter(symbol_info, "PRICE_FILTER")

        result = SymbolInfo(
            symbol=symbol,
            base_asset=symbol_info["baseAsset"],
            quote_asset=symbol_info["quoteAsset"],
            min_qty=Decimal(lot_size.get("minQty", "0.00000001")),
            max_qty=Decimal(lot_size.get("maxQty", "99999999")),
            step_size=Decimal(lot_size.get("stepSize", "0.00000001")),
            min_notional=Decimal(
                min_notional_filter.get("minNotional", "10") if min_notional_filter else "10"
            ),
            tick_size=Decimal(price_filter.get("tickSize", "0.01") if price_filter else "0.01"),
        )

        # Cache
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
        tickers_data = await self.client.get_all_tickers()
        now = datetime.now(timezone.utc)
        return [
            Ticker(
                symbol=t["symbol"],
                price=Decimal(t["price"]),
                bid=Decimal("0"),  # Not available in all_tickers
                ask=Decimal("0"),
                volume_24h=Decimal("0"),
                timestamp=now,
            )
            for t in tickers_data
        ]

    @staticmethod
    def _parse_kline(symbol: str, interval: str, raw: list) -> Kline:
        return Kline(
            symbol=symbol,
            interval=interval,
            open_time=datetime.fromtimestamp(raw[0] / 1000, tz=timezone.utc),
            open=Decimal(str(raw[1])),
            high=Decimal(str(raw[2])),
            low=Decimal(str(raw[3])),
            close=Decimal(str(raw[4])),
            volume=Decimal(str(raw[5])),
            close_time=datetime.fromtimestamp(raw[6] / 1000, tz=timezone.utc),
        )

    @staticmethod
    def _get_filter(symbol_info: dict, filter_type: str) -> dict | None:
        for f in symbol_info.get("filters", []):
            if f["filterType"] == filter_type:
                return f
        return None
