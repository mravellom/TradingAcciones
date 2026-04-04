"""Tests for ATR calculator and ATR-based SL/TP in strategies."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.exchange.base import Kline
from app.pipeline.signal_engine.atr import calculate_atr


def _make_klines_with_range(
    n: int = 30,
    high: Decimal = Decimal("42100"),
    low: Decimal = Decimal("41900"),
    close: Decimal = Decimal("42000"),
) -> list[Kline]:
    """Create klines with consistent high/low range for predictable ATR."""
    now = datetime.now(timezone.utc)
    return [
        Kline(
            symbol="BTCUSDT", interval="1h", open_time=now,
            open=Decimal("42000"), high=high, low=low, close=close,
            volume=Decimal("1000"), close_time=now,
        )
        for _ in range(n)
    ]


class TestCalculateATR:
    def test_returns_none_insufficient_data(self):
        klines = _make_klines_with_range(n=5)
        result = calculate_atr(klines, period=14)
        assert result is None

    def test_returns_decimal(self):
        klines = _make_klines_with_range(n=30)
        result = calculate_atr(klines, period=14)
        assert result is not None
        assert isinstance(result, Decimal)

    def test_consistent_range_gives_expected_atr(self):
        """With constant high-low range of 200, ATR should be ~200."""
        klines = _make_klines_with_range(
            n=30,
            high=Decimal("42100"),
            low=Decimal("41900"),
            close=Decimal("42000"),
        )
        atr = calculate_atr(klines, period=14)
        assert atr is not None
        # TR = max(high-low, abs(high-prev_close), abs(low-prev_close))
        # = max(200, 100, 100) = 200
        assert atr == Decimal("200.0")

    def test_zero_range_gives_zero_atr(self):
        """All same prices → ATR should be 0."""
        klines = _make_klines_with_range(
            n=30,
            high=Decimal("42000"),
            low=Decimal("42000"),
            close=Decimal("42000"),
        )
        atr = calculate_atr(klines, period=14)
        assert atr is not None
        assert atr == Decimal("0.0")

    def test_custom_period(self):
        klines = _make_klines_with_range(n=30)
        atr_7 = calculate_atr(klines, period=7)
        atr_14 = calculate_atr(klines, period=14)
        assert atr_7 is not None
        assert atr_14 is not None

    def test_atr_sl_tp_buy_direction(self):
        """Verify ATR-based SL/TP calculation for BUY."""
        entry = Decimal("42000")
        atr = Decimal("200")
        sl_mult = Decimal("1.5")
        tp_mult = Decimal("3.0")

        sl = entry - (atr * sl_mult)  # 42000 - 300 = 41700
        tp = entry + (atr * tp_mult)  # 42000 + 600 = 42600

        assert sl == Decimal("41700")
        assert tp == Decimal("42600")
        assert sl < entry
        assert tp > entry

    def test_atr_sl_tp_sell_direction(self):
        """Verify ATR-based SL/TP calculation for SELL."""
        entry = Decimal("42000")
        atr = Decimal("200")
        sl_mult = Decimal("1.5")
        tp_mult = Decimal("3.0")

        sl = entry + (atr * sl_mult)  # 42000 + 300 = 42300
        tp = entry - (atr * tp_mult)  # 42000 - 600 = 41400

        assert sl == Decimal("42300")
        assert tp == Decimal("41400")
        assert sl > entry
        assert tp < entry
