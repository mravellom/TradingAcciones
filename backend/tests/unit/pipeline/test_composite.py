from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.signal_engine.base import SignalGenerator, SignalResult
from app.pipeline.signal_engine.composite import CompositeSignalGenerator


def _make_klines(n: int = 30) -> list[Kline]:
    now = datetime.now(timezone.utc)
    return [
        Kline(
            symbol="BTCUSDT", interval="1h", open_time=now,
            open=Decimal("42000"), high=Decimal("42100"),
            low=Decimal("41900"), close=Decimal("42000"),
            volume=Decimal("1000"), close_time=now,
        )
        for _ in range(n)
    ]


class FakeGenerator(SignalGenerator):
    """Fake signal generator for testing."""

    def __init__(self, name: str, result: SignalResult | None = None, should_raise: bool = False):
        self._name = name
        self._result = result
        self._should_raise = should_raise

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, symbol, klines):
        if self._should_raise:
            raise RuntimeError("Generator exploded")
        return self._result


class TestCompositeSignalGenerator:
    @pytest.mark.asyncio
    async def test_no_signals_returns_none(self):
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("a", result=None), 1.0),
                (FakeGenerator("b", result=None), 1.0),
            ]
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert result is None

    @pytest.mark.asyncio
    async def test_agreement_combines_confidence(self):
        sig_a = SignalResult(
            symbol="BTCUSDT", signal_type=SignalType.BUY,
            confidence=Decimal("0.8"), indicators={"rsi": 25},
            entry_price=Decimal("42000"), stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
        )
        sig_b = SignalResult(
            symbol="BTCUSDT", signal_type=SignalType.BUY,
            confidence=Decimal("0.7"), indicators={"sma_cross": True},
            entry_price=Decimal("42000"), stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
        )
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("a", result=sig_a), 0.4),
                (FakeGenerator("b", result=sig_b), 0.6),
            ]
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert result is not None
        assert result.signal_type == SignalType.BUY
        # Weighted: 0.8 * 0.4 + 0.7 * 0.6 = 0.32 + 0.42 = 0.74
        assert result.confidence == Decimal("0.74")

    @pytest.mark.asyncio
    async def test_disagreement_returns_none(self):
        sig_buy = SignalResult(
            symbol="BTCUSDT", signal_type=SignalType.BUY,
            confidence=Decimal("0.8"), entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"), take_profit=Decimal("44000"),
        )
        sig_sell = SignalResult(
            symbol="BTCUSDT", signal_type=SignalType.SELL,
            confidence=Decimal("0.8"), entry_price=Decimal("42000"),
            stop_loss=Decimal("43000"), take_profit=Decimal("40000"),
        )
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("a", result=sig_buy), 0.5),
                (FakeGenerator("b", result=sig_sell), 0.5),
            ]
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert result is None

    @pytest.mark.asyncio
    async def test_below_min_confidence_returns_none(self):
        sig = SignalResult(
            symbol="BTCUSDT", signal_type=SignalType.BUY,
            confidence=Decimal("0.5"), entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"), take_profit=Decimal("44000"),
        )
        composite = CompositeSignalGenerator(
            generators=[(FakeGenerator("a", result=sig), 1.0)],
            min_confidence=Decimal("0.6"),
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert result is None

    @pytest.mark.asyncio
    async def test_failing_generator_ignored(self):
        sig = SignalResult(
            symbol="BTCUSDT", signal_type=SignalType.BUY,
            confidence=Decimal("0.8"), entry_price=Decimal("42000"),
            stop_loss=Decimal("41000"), take_profit=Decimal("44000"),
        )
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("good", result=sig), 0.5),
                (FakeGenerator("bad", should_raise=True), 0.5),
            ]
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        # Only the good generator's signal is used
        assert result is not None
        assert result.signal_type == SignalType.BUY

    @pytest.mark.asyncio
    async def test_merges_indicators(self):
        sig_a = SignalResult(
            symbol="BTCUSDT", signal_type=SignalType.BUY,
            confidence=Decimal("0.8"), indicators={"rsi": 25},
            entry_price=Decimal("42000"), stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
        )
        sig_b = SignalResult(
            symbol="BTCUSDT", signal_type=SignalType.BUY,
            confidence=Decimal("0.7"), indicators={"sma_fast": 41500},
            entry_price=Decimal("42000"), stop_loss=Decimal("41000"),
            take_profit=Decimal("44000"),
        )
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("a", result=sig_a), 0.5),
                (FakeGenerator("b", result=sig_b), 0.5),
            ]
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert "rsi" in result.indicators
        assert "sma_fast" in result.indicators
