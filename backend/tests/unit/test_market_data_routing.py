"""Tests for MarketDataService multi-exchange routing."""
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.exchange.base import ExchangeClient, Kline, Ticker
from app.services.market_data import MarketDataService


def _make_ticker(symbol: str) -> Ticker:
    return Ticker(
        symbol=symbol,
        price=Decimal("150.00"),
        bid=Decimal("149.95"),
        ask=Decimal("150.05"),
        volume_24h=Decimal("5000000"),
        timestamp=datetime.now(timezone.utc),
    )


def _make_kline(symbol: str) -> Kline:
    now = datetime.now(timezone.utc)
    return Kline(
        symbol=symbol, interval="1d", open_time=now,
        open=Decimal("148"), high=Decimal("152"),
        low=Decimal("147"), close=Decimal("150"),
        volume=Decimal("1000000"), close_time=now,
    )


class TestMarketDataRouting:
    @pytest.fixture
    def crypto_exchange(self):
        mock = AsyncMock(spec=ExchangeClient)
        mock.get_ticker.return_value = _make_ticker("BTCUSDT")
        mock.get_klines.return_value = [_make_kline("BTCUSDT")]
        return mock

    @pytest.fixture
    def stock_exchange(self):
        mock = AsyncMock(spec=ExchangeClient)
        mock.get_ticker.return_value = _make_ticker("AAPL")
        mock.get_klines.return_value = [_make_kline("AAPL")]
        return mock

    @pytest.fixture
    def svc_both(self, crypto_exchange, stock_exchange):
        """Service with both exchanges, manually setting stock symbols."""
        svc = MarketDataService.__new__(MarketDataService)
        svc._exchange = crypto_exchange
        svc._stock_exchange = stock_exchange
        svc._stock_symbols = {"AAPL", "MSFT"}
        svc._redis = AsyncMock()
        svc._redis.hgetall.return_value = {}
        return svc

    @pytest.fixture
    def svc_crypto_only(self, crypto_exchange):
        """Service with only crypto exchange."""
        svc = MarketDataService.__new__(MarketDataService)
        svc._exchange = crypto_exchange
        svc._stock_exchange = None
        svc._stock_symbols = set()
        svc._redis = AsyncMock()
        svc._redis.hgetall.return_value = {}
        return svc

    def test_routes_crypto_to_binance(self, svc_both, crypto_exchange):
        assert svc_both._get_exchange("BTCUSDT") is crypto_exchange

    def test_routes_stock_to_alpaca(self, svc_both, stock_exchange):
        assert svc_both._get_exchange("AAPL") is stock_exchange

    def test_routes_msft_to_alpaca(self, svc_both, stock_exchange):
        assert svc_both._get_exchange("MSFT") is stock_exchange

    def test_routes_unknown_to_crypto(self, svc_both, crypto_exchange):
        assert svc_both._get_exchange("ETHUSDT") is crypto_exchange

    def test_no_stock_exchange_falls_back(self, svc_crypto_only, crypto_exchange):
        assert svc_crypto_only._get_exchange("AAPL") is crypto_exchange

    @pytest.mark.asyncio
    async def test_get_ticker_routes_stock(self, svc_both, stock_exchange):
        await svc_both.get_ticker("AAPL")
        stock_exchange.get_ticker.assert_called_once_with("AAPL")

    @pytest.mark.asyncio
    async def test_get_ticker_routes_crypto(self, svc_both, crypto_exchange):
        await svc_both.get_ticker("BTCUSDT")
        crypto_exchange.get_ticker.assert_called_once_with("BTCUSDT")

    @pytest.mark.asyncio
    async def test_get_klines_routes_stock(self, svc_both, stock_exchange):
        await svc_both.get_klines("MSFT", "1d", 50)
        stock_exchange.get_klines.assert_called_once_with("MSFT", "1d", 50)

    @pytest.mark.asyncio
    async def test_get_market_snapshot_stock_class(self, svc_both, stock_exchange):
        stock_exchange.get_ticker.return_value = _make_ticker("AAPL")
        snapshot = await svc_both.get_market_snapshot("AAPL")
        assert snapshot["asset_class"] == "STOCKS"

    @pytest.mark.asyncio
    async def test_get_market_snapshot_crypto_class(self, svc_both, crypto_exchange):
        crypto_exchange.get_ticker.return_value = _make_ticker("BTCUSDT")
        snapshot = await svc_both.get_market_snapshot("BTCUSDT")
        assert snapshot["asset_class"] == "CRYPTO"
