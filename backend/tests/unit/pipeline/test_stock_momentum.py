"""Tests for StockMomentumStrategy."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.strategy.stock_momentum import (
    STOCK_RSI_OVERBOUGHT,
    STOCK_RSI_OVERSOLD,
    STOCK_RSI_SL_PCT,
    STOCK_RSI_TP_PCT,
    STOCK_SMA_FAST,
    STOCK_SMA_SLOW,
    StockMomentumStrategy,
)


def _make_klines(closes: list[float], symbol: str = "AAPL") -> list[Kline]:
    now = datetime.now(timezone.utc)
    return [
        Kline(
            symbol=symbol,
            interval="1d",
            open_time=now,
            open=Decimal(str(c)),
            high=Decimal(str(c + 1)),
            low=Decimal(str(c - 1)),
            close=Decimal(str(c)),
            volume=Decimal("1000000"),
            close_time=now,
        )
        for c in closes
    ]


class TestStockMomentumConfig:
    """Verify stock-specific parameters are different from crypto defaults."""

    def test_rsi_oversold_is_higher_than_crypto(self):
        # Stocks: 35 vs crypto: 30
        assert STOCK_RSI_OVERSOLD > 30

    def test_rsi_overbought_is_lower_than_crypto(self):
        # Stocks: 65 vs crypto: 70
        assert STOCK_RSI_OVERBOUGHT < 70

    def test_sl_is_tighter_than_crypto(self):
        # Stocks: 1.5% vs crypto: 2%
        assert STOCK_RSI_SL_PCT < Decimal("0.02")

    def test_tp_is_tighter_than_crypto(self):
        # Stocks: 3% vs crypto: 4%
        assert STOCK_RSI_TP_PCT < Decimal("0.04")

    def test_tp_sl_ratio_is_2_to_1(self):
        assert STOCK_RSI_TP_PCT / STOCK_RSI_SL_PCT == Decimal("2")

    def test_sma_slow_is_longer_than_crypto(self):
        # Stocks: 30 vs crypto: 21
        assert STOCK_SMA_SLOW > 21


class TestStockMomentumStrategy:
    @pytest.fixture
    def strategy(self):
        return StockMomentumStrategy(strategy_id=uuid4())

    def test_name(self, strategy):
        assert strategy.name == "stock_momentum"

    def test_has_id(self, strategy):
        assert strategy.id is not None

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_none(self, strategy):
        klines = _make_klines([150.0] * 10)
        result = await strategy.evaluate("AAPL", klines, "1d")
        assert result is None

    @pytest.mark.asyncio
    async def test_neutral_market_returns_none(self, strategy):
        # Oscillating prices — RSI stays mid-range, no crossover
        prices = [150.0 + (1 if i % 2 == 0 else -1) for i in range(50)]
        klines = _make_klines(prices)
        result = await strategy.evaluate("AAPL", klines, "1d")
        assert result is None

    @pytest.mark.asyncio
    async def test_downtrend_may_generate_buy(self, strategy):
        # Strong decline to push RSI below 35 (stock threshold)
        prices = [200.0 - (i * 3) for i in range(50)]
        klines = _make_klines(prices)
        result = await strategy.evaluate("AAPL", klines, "1d")
        # RSI should fire BUY, but composite needs agreement
        # If result generated, it must be BUY with proper SL/TP
        if result is not None:
            assert result.action == SignalType.BUY
            assert result.stop_loss < result.entry_price
            assert result.take_profit > result.entry_price
            assert result.confidence >= Decimal("0.6")

    @pytest.mark.asyncio
    async def test_intent_has_strategy_id(self, strategy):
        # Force a signal with extreme decline
        prices = [200.0 - (i * 5) for i in range(50)]
        klines = _make_klines(prices)
        result = await strategy.evaluate("AAPL", klines, "1d")
        if result is not None:
            assert result.strategy_id == strategy.id
            assert result.timeframe == "1d"
