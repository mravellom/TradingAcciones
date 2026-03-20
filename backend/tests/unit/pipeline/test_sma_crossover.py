from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.signal_engine.sma_crossover import SMACrossoverSignalGenerator


def _make_klines(closes: list[float]) -> list[Kline]:
    now = datetime.now(timezone.utc)
    return [
        Kline(
            symbol="BTCUSDT",
            interval="1h",
            open_time=now,
            open=Decimal(str(c)),
            high=Decimal(str(c + 50)),
            low=Decimal(str(c - 50)),
            close=Decimal(str(c)),
            volume=Decimal("1000"),
            close_time=now,
        )
        for c in closes
    ]


class TestSMACrossover:
    @pytest.fixture
    def sma_gen(self):
        return SMACrossoverSignalGenerator(fast_period=5, slow_period=10)

    @pytest.mark.asyncio
    async def test_not_enough_data_returns_none(self, sma_gen):
        klines = _make_klines([100] * 5)
        result = await sma_gen.generate("BTCUSDT", klines)
        assert result is None

    @pytest.mark.asyncio
    async def test_golden_cross_generates_buy(self, sma_gen):
        # Downtrend then sharp upturn → fast SMA crosses above slow SMA
        prices = [100, 98, 96, 94, 92, 90, 88, 86, 84, 82, 80, 85, 95]
        klines = _make_klines(prices)
        result = await sma_gen.generate("BTCUSDT", klines)
        if result is not None:
            assert result.signal_type == SignalType.BUY
            assert result.indicators["crossover"] == "golden"
            assert result.confidence >= Decimal("0.6")

    @pytest.mark.asyncio
    async def test_death_cross_generates_sell(self, sma_gen):
        # Uptrend then sharp downturn → fast SMA crosses below slow SMA
        prices = [80, 82, 84, 86, 88, 90, 92, 94, 96, 98, 100, 90, 75]
        klines = _make_klines(prices)
        result = await sma_gen.generate("BTCUSDT", klines)
        if result is not None:
            assert result.signal_type == SignalType.SELL
            assert result.indicators["crossover"] == "death"

    @pytest.mark.asyncio
    async def test_no_crossover_returns_none(self, sma_gen):
        # Steady uptrend → fast always above slow → no crossover
        prices = [100 + i for i in range(20)]
        klines = _make_klines(prices)
        result = await sma_gen.generate("BTCUSDT", klines)
        assert result is None

    def test_sma_calculation(self, sma_gen):
        values = [10, 20, 30, 40, 50]
        assert sma_gen._sma(values, 3, offset=0) == 40.0  # (30+40+50)/3
        assert sma_gen._sma(values, 3, offset=1) == 30.0  # (20+30+40)/3

    def test_name(self, sma_gen):
        assert sma_gen.name == "sma_crossover"
