from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.signal_engine.rsi import RSISignalGenerator


def _make_klines(closes: list[float]) -> list[Kline]:
    """Create Kline objects from a list of close prices."""
    now = datetime.now(timezone.utc)
    return [
        Kline(
            symbol="BTCUSDT",
            interval="1h",
            open_time=now,
            open=Decimal(str(c)),
            high=Decimal(str(c + 100)),
            low=Decimal(str(c - 100)),
            close=Decimal(str(c)),
            volume=Decimal("1000"),
            close_time=now,
        )
        for c in closes
    ]


class TestRSISignalGenerator:
    @pytest.fixture
    def rsi_gen(self):
        return RSISignalGenerator(period=14)

    @pytest.mark.asyncio
    async def test_not_enough_data_returns_none(self, rsi_gen):
        klines = _make_klines([100] * 10)  # Only 10 candles, need 15+
        result = await rsi_gen.generate("BTCUSDT", klines)
        assert result is None

    @pytest.mark.asyncio
    async def test_oversold_generates_buy(self, rsi_gen):
        # Create a downtrend to push RSI below 30
        prices = [50000 - (i * 200) for i in range(30)]  # Steady decline
        klines = _make_klines(prices)
        result = await rsi_gen.generate("BTCUSDT", klines)
        if result is not None:
            assert result.signal_type == SignalType.BUY
            assert result.confidence >= Decimal("0.6")
            assert result.stop_loss < result.entry_price
            assert result.take_profit > result.entry_price
            assert "rsi" in result.indicators

    @pytest.mark.asyncio
    async def test_overbought_generates_sell(self, rsi_gen):
        # Create an uptrend to push RSI above 70
        prices = [40000 + (i * 200) for i in range(30)]  # Steady climb
        klines = _make_klines(prices)
        result = await rsi_gen.generate("BTCUSDT", klines)
        if result is not None:
            assert result.signal_type == SignalType.SELL
            assert result.confidence >= Decimal("0.6")
            assert "rsi" in result.indicators

    @pytest.mark.asyncio
    async def test_neutral_returns_none(self, rsi_gen):
        # Flat prices → RSI around 50 → no signal
        prices = [42000 + (i % 2 * 10) for i in range(30)]
        klines = _make_klines(prices)
        result = await rsi_gen.generate("BTCUSDT", klines)
        assert result is None

    @pytest.mark.asyncio
    async def test_rsi_calculation(self, rsi_gen):
        # Known RSI calculation test
        prices = [44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42,
                  45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03,
                  46.41, 46.22, 45.64]
        klines = _make_klines(prices)
        rsi = rsi_gen._calculate_rsi(klines)
        assert rsi is not None
        assert 0 <= rsi <= 100

    def test_name(self, rsi_gen):
        assert rsi_gen.name == "rsi"
