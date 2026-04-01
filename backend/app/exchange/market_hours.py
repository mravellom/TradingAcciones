"""US stock market hours utilities with holiday support.

Uses Alpaca's /v2/calendar endpoint to determine actual trading days,
so holidays like Memorial Day, Thanksgiving, etc. are handled correctly.
Falls back to weekday-only check if Alpaca is unavailable.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.logging import get_logger

logger = get_logger(__name__)

ET = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# In-memory cache: set of trading dates (date objects)
_trading_days_cache: set[date] | None = None
_cache_year: int | None = None


def _load_trading_calendar(year: int | None = None) -> set[date]:
    """Load trading calendar from Alpaca. Returns set of valid trading dates."""
    global _trading_days_cache, _cache_year

    year = year or datetime.now(ET).year
    if _trading_days_cache is not None and _cache_year == year:
        return _trading_days_cache

    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetCalendarRequest
        from app.config import settings

        if not settings.alpaca_api_key:
            raise ValueError("No Alpaca API key configured")

        client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_api_secret,
            paper=True,
        )
        filters = GetCalendarRequest(
            start=date(year, 1, 1),
            end=date(year, 12, 31),
        )
        calendar = client.get_calendar(filters)
        trading_dates = set()
        for day in calendar:
            if isinstance(day.date, date):
                trading_dates.add(day.date)
            else:
                trading_dates.add(date.fromisoformat(str(day.date)))

        _trading_days_cache = trading_dates
        _cache_year = year
        logger.info("trading_calendar_loaded", year=year, trading_days=len(trading_dates))
        return trading_dates

    except Exception as e:
        logger.warning("trading_calendar_unavailable", error=str(e), fallback="weekday_only")
        return set()


def is_trading_day(d: date | None = None) -> bool:
    """Check if a date is a US stock trading day.

    Uses Alpaca calendar if available, falls back to weekday check.
    """
    d = d or datetime.now(ET).date()

    calendar = _load_trading_calendar(d.year)
    if calendar:
        return d in calendar

    # Fallback: weekday check only (no holiday awareness)
    return d.weekday() <= 4


def is_us_market_open(now: datetime | None = None) -> bool:
    """Check if US stock market is currently open.

    Checks: trading day (holidays) + time within 9:30-16:00 ET.
    """
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)

    if not is_trading_day(now.date()):
        return False

    current_time = now.time()
    return MARKET_OPEN <= current_time < MARKET_CLOSE


def next_market_open(now: datetime | None = None) -> datetime:
    """Return the next market open datetime in ET.

    Skips weekends and holidays using Alpaca calendar.
    """
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)

    candidate = now.replace(hour=9, minute=30, second=0, microsecond=0)

    # If we're past today's open, move to next day
    if now.time() >= MARKET_OPEN:
        candidate += timedelta(days=1)

    # Skip non-trading days (weekends + holidays)
    max_skip = 14  # Never skip more than 2 weeks
    for _ in range(max_skip):
        if is_trading_day(candidate.date()):
            return candidate
        candidate += timedelta(days=1)

    return candidate


def clear_calendar_cache() -> None:
    """Clear the cached trading calendar. Useful for testing."""
    global _trading_days_cache, _cache_year
    _trading_days_cache = None
    _cache_year = None
