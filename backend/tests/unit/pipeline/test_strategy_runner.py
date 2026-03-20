import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.enums import SignalType
from app.exchange.base import Kline
from app.pipeline.strategy.base import Strategy, TradeIntent
from app.pipeline.strategy.runner import StrategyRunner


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


class FakeStrategy(Strategy):
    def __init__(self, name: str, intent: TradeIntent | None = None, delay: float = 0, error: bool = False):
        self._id = uuid4()
        self._name = name
        self._intent = intent
        self._delay = delay
        self._error = error

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    async def evaluate(self, symbol, klines, timeframe):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise RuntimeError("Strategy crashed")
        return self._intent


def _make_intent(strategy_id=None) -> TradeIntent:
    return TradeIntent(
        symbol="BTCUSDT",
        action=SignalType.BUY,
        confidence=Decimal("0.75"),
        entry_price=Decimal("42000"),
        stop_loss=Decimal("41000"),
        take_profit=Decimal("44000"),
        strategy_id=strategy_id or uuid4(),
        timeframe="1h",
        indicators={"test": True},
    )


class TestStrategyRunner:
    @pytest.mark.asyncio
    async def test_runs_all_strategies(self):
        s1 = FakeStrategy("a", intent=_make_intent())
        s2 = FakeStrategy("b", intent=_make_intent())
        runner = StrategyRunner()

        intents = await runner.run_all([s1, s2], "BTCUSDT", _make_klines(), "1h")
        assert len(intents) == 2

    @pytest.mark.asyncio
    async def test_failing_strategy_doesnt_block_others(self):
        good = FakeStrategy("good", intent=_make_intent())
        bad = FakeStrategy("bad", error=True)
        runner = StrategyRunner()

        intents = await runner.run_all([good, bad], "BTCUSDT", _make_klines(), "1h")
        assert len(intents) == 1

    @pytest.mark.asyncio
    async def test_timeout_strategy_doesnt_block(self):
        fast = FakeStrategy("fast", intent=_make_intent())
        slow = FakeStrategy("slow", intent=_make_intent(), delay=10)
        runner = StrategyRunner(timeout=1)

        intents = await runner.run_all([fast, slow], "BTCUSDT", _make_klines(), "1h")
        assert len(intents) == 1

    @pytest.mark.asyncio
    async def test_auto_deactivate_after_3_failures(self):
        bad = FakeStrategy("bad", error=True)
        runner = StrategyRunner()

        for _ in range(3):
            await runner.run_all([bad], "BTCUSDT", _make_klines(), "1h")

        assert not runner.is_active(str(bad.id))

        # Deactivated strategy should not run
        intents = await runner.run_all([bad], "BTCUSDT", _make_klines(), "1h")
        assert len(intents) == 0

    @pytest.mark.asyncio
    async def test_reactivate_strategy(self):
        bad = FakeStrategy("bad", error=True)
        runner = StrategyRunner()

        for _ in range(3):
            await runner.run_all([bad], "BTCUSDT", _make_klines(), "1h")
        assert not runner.is_active(str(bad.id))

        runner.reactivate(str(bad.id))
        assert runner.is_active(str(bad.id))

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        sid = uuid4()
        bad = FakeStrategy("flaky", error=True)
        bad._id = sid
        runner = StrategyRunner()

        # 2 failures
        await runner.run_all([bad], "BTCUSDT", _make_klines(), "1h")
        await runner.run_all([bad], "BTCUSDT", _make_klines(), "1h")

        # Success resets
        good = FakeStrategy("flaky", intent=_make_intent(sid))
        good._id = sid
        await runner.run_all([good], "BTCUSDT", _make_klines(), "1h")

        # 2 more failures should not deactivate (reset happened)
        bad._id = sid
        await runner.run_all([bad], "BTCUSDT", _make_klines(), "1h")
        await runner.run_all([bad], "BTCUSDT", _make_klines(), "1h")
        assert runner.is_active(str(sid))

    @pytest.mark.asyncio
    async def test_none_intent_filtered(self):
        s1 = FakeStrategy("a", intent=None)
        s2 = FakeStrategy("b", intent=_make_intent())
        runner = StrategyRunner()

        intents = await runner.run_all([s1, s2], "BTCUSDT", _make_klines(), "1h")
        assert len(intents) == 1
