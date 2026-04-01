"""Tests for US market hours utilities."""
from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.exchange.market_hours import (
    ET,
    clear_calendar_cache,
    is_trading_day,
    is_us_market_open,
    next_market_open,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear calendar cache before each test."""
    clear_calendar_cache()
    yield
    clear_calendar_cache()


def _patch_calendar(trading_dates: set[date]):
    """Patch _load_trading_calendar to return specific dates."""
    return patch(
        "app.exchange.market_hours._load_trading_calendar",
        return_value=trading_dates,
    )


# A set of "normal" April 2026 trading days (Mon-Fri, no holidays)
APRIL_2026_TRADING_DAYS = {
    date(2026, 4, d) for d in range(1, 31)
    if date(2026, 4, d).weekday() <= 4
}


class TestIsUSMarketOpen:
    def test_open_during_trading_hours(self):
        dt = datetime(2026, 4, 1, 10, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is True

    def test_open_at_market_open(self):
        dt = datetime(2026, 4, 1, 9, 30, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is True

    def test_closed_at_market_close(self):
        dt = datetime(2026, 4, 1, 16, 0, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is False

    def test_closed_before_open(self):
        dt = datetime(2026, 4, 1, 9, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is False

    def test_closed_after_close(self):
        dt = datetime(2026, 4, 1, 17, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is False

    def test_closed_on_saturday(self):
        dt = datetime(2026, 4, 4, 12, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is False

    def test_closed_on_sunday(self):
        dt = datetime(2026, 4, 5, 12, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is False

    def test_open_on_friday(self):
        dt = datetime(2026, 4, 3, 12, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is True

    def test_handles_utc_timezone(self):
        utc = ZoneInfo("UTC")
        dt = datetime(2026, 4, 1, 14, 0, tzinfo=utc)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is True

    def test_handles_naive_datetime(self):
        dt = datetime(2026, 4, 1, 12, 0)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is True

    def test_one_minute_before_close(self):
        dt = datetime(2026, 4, 1, 15, 59, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_us_market_open(dt) is True


class TestHolidays:
    def test_closed_on_holiday(self):
        """Market is closed on a holiday even if it's a weekday."""
        # Remove April 10 (Friday) to simulate a holiday like Good Friday
        trading_days = APRIL_2026_TRADING_DAYS - {date(2026, 4, 10)}
        dt = datetime(2026, 4, 10, 12, 0, tzinfo=ET)
        with _patch_calendar(trading_days):
            assert is_us_market_open(dt) is False

    def test_is_trading_day_false_on_holiday(self):
        trading_days = APRIL_2026_TRADING_DAYS - {date(2026, 4, 10)}
        with _patch_calendar(trading_days):
            assert is_trading_day(date(2026, 4, 10)) is False

    def test_is_trading_day_true_on_normal_day(self):
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            assert is_trading_day(date(2026, 4, 1)) is True

    def test_next_open_skips_holiday(self):
        """next_market_open should skip holidays."""
        # Remove Friday April 10 — next open should be Monday April 13
        trading_days = APRIL_2026_TRADING_DAYS - {date(2026, 4, 10)}
        dt = datetime(2026, 4, 9, 17, 0, tzinfo=ET)  # Thursday after close
        with _patch_calendar(trading_days):
            result = next_market_open(dt)
            # Friday is a holiday, so next open is Monday
            assert result.date() == date(2026, 4, 13)
            assert result.hour == 9
            assert result.minute == 30

    def test_fallback_when_no_calendar(self):
        """When calendar is empty (Alpaca unavailable), fall back to weekday check."""
        with _patch_calendar(set()):
            # Weekday should still work
            assert is_trading_day(date(2026, 4, 1)) is True   # Wednesday
            assert is_trading_day(date(2026, 4, 4)) is False  # Saturday


class TestNextMarketOpen:
    def test_next_open_from_morning(self):
        dt = datetime(2026, 4, 1, 8, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            result = next_market_open(dt)
            assert result.hour == 9
            assert result.minute == 30
            assert result.day == 1

    def test_next_open_from_afternoon(self):
        dt = datetime(2026, 4, 1, 14, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            result = next_market_open(dt)
            assert result.day == 2
            assert result.hour == 9

    def test_next_open_from_friday_afternoon(self):
        dt = datetime(2026, 4, 3, 14, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            result = next_market_open(dt)
            assert result.weekday() == 0  # Monday
            assert result.day == 6

    def test_next_open_from_saturday(self):
        dt = datetime(2026, 4, 4, 12, 0, tzinfo=ET)
        with _patch_calendar(APRIL_2026_TRADING_DAYS):
            result = next_market_open(dt)
            assert result.weekday() == 0  # Monday
            assert result.hour == 9
            assert result.minute == 30
