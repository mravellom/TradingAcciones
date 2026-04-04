"""Tests for CompositeSignalGenerator with partial signal agreement."""
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
    def __init__(self, name: str, result: SignalResult | None = None):
        self._name = name
        self._result = result

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, symbol, klines):
        return self._result


def _signal(signal_type: SignalType, confidence: str = "0.75") -> SignalResult:
    return SignalResult(
        symbol="BTCUSDT",
        signal_type=signal_type,
        confidence=Decimal(confidence),
        indicators={},
        entry_price=Decimal("42000"),
        stop_loss=Decimal("41000") if signal_type == SignalType.BUY else Decimal("43000"),
        take_profit=Decimal("44000") if signal_type == SignalType.BUY else Decimal("40000"),
    )


class TestPartialAgreement:
    @pytest.mark.asyncio
    async def test_2_buy_1_sell_with_min_2_generates_buy(self):
        """2 BUY + 1 SELL with min_agreeing=2 → should produce BUY."""
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("rsi", _signal(SignalType.BUY, "0.80")), 0.4),
                (FakeGenerator("sma", _signal(SignalType.BUY, "0.70")), 0.4),
                (FakeGenerator("ml", _signal(SignalType.SELL, "0.65")), 0.2),
            ],
            min_confidence=Decimal("0.5"),
            min_agreeing_signals=2,
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert result is not None
        assert result.signal_type == SignalType.BUY

    @pytest.mark.asyncio
    async def test_2_buy_1_sell_with_min_3_returns_none(self):
        """2 BUY + 1 SELL with min_agreeing=3 (unanimous) → should return None."""
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("rsi", _signal(SignalType.BUY)), 0.4),
                (FakeGenerator("sma", _signal(SignalType.BUY)), 0.4),
                (FakeGenerator("ml", _signal(SignalType.SELL)), 0.2),
            ],
            min_confidence=Decimal("0.5"),
            min_agreeing_signals=3,
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert result is None

    @pytest.mark.asyncio
    async def test_1_buy_1_sell_1_none_with_min_2_returns_none(self):
        """1 BUY + 1 SELL + 1 None with min_agreeing=2 → insufficient agreement."""
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("rsi", _signal(SignalType.BUY)), 0.4),
                (FakeGenerator("sma", _signal(SignalType.SELL)), 0.4),
                (FakeGenerator("ml", None), 0.2),
            ],
            min_confidence=Decimal("0.5"),
            min_agreeing_signals=2,
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert result is None

    @pytest.mark.asyncio
    async def test_partial_agreement_uses_only_agreeing_weights(self):
        """Only agreeing generators should contribute to confidence."""
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("rsi", _signal(SignalType.BUY, "0.80")), 0.5),
                (FakeGenerator("sma", _signal(SignalType.BUY, "0.70")), 0.3),
                (FakeGenerator("ml", _signal(SignalType.SELL, "0.90")), 0.2),
            ],
            min_confidence=Decimal("0.5"),
            min_agreeing_signals=2,
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert result is not None
        assert result.signal_type == SignalType.BUY
        # Only rsi (0.5) and sma (0.3) contribute, renormalized:
        # rsi_norm = 0.5/0.8 = 0.625, sma_norm = 0.3/0.8 = 0.375
        # confidence = 0.80 * 0.625 + 0.70 * 0.375 = 0.50 + 0.2625 = 0.7625
        assert result.confidence == Decimal("0.7625")

    @pytest.mark.asyncio
    async def test_no_min_agreeing_requires_unanimity(self):
        """Default (min_agreeing_signals=None) requires all to agree."""
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("rsi", _signal(SignalType.BUY)), 0.5),
                (FakeGenerator("sma", _signal(SignalType.SELL)), 0.5),
            ],
            min_confidence=Decimal("0.5"),
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert result is None

    @pytest.mark.asyncio
    async def test_all_agree_works_with_partial_setting(self):
        """All generators agree even when partial is enabled → should still work."""
        composite = CompositeSignalGenerator(
            generators=[
                (FakeGenerator("rsi", _signal(SignalType.BUY, "0.80")), 0.4),
                (FakeGenerator("sma", _signal(SignalType.BUY, "0.70")), 0.3),
                (FakeGenerator("ml", _signal(SignalType.BUY, "0.75")), 0.3),
            ],
            min_confidence=Decimal("0.5"),
            min_agreeing_signals=2,
        )
        result = await composite.generate("BTCUSDT", _make_klines())
        assert result is not None
        assert result.signal_type == SignalType.BUY
