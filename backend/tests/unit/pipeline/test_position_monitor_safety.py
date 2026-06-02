"""Tests for position monitor safety features.

Validates:
- Stale price rejection (>15s old)
- Deduplication prevents double-closing the same position
- execution_mode comes from position, not from the monitor
"""
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.enums import ExecutionMode, PositionStatus
from app.tasks.position_monitor import (
    CLOSE_DEDUP_TTL,
    MAX_PRICE_STALE_SECONDS,
    PositionMonitor,
)


def _make_position(**overrides):
    """Create a mock Position with sensible defaults."""
    pos = MagicMock()
    pos.id = overrides.get("id", "pos-001")
    pos.symbol = overrides.get("symbol", "BTCUSDT")
    pos.side = overrides.get("side", "LONG")
    pos.status = overrides.get("status", PositionStatus.OPEN.value)
    pos.entry_price = overrides.get("entry_price", Decimal("50000"))
    pos.current_price = overrides.get("current_price", Decimal("50000"))
    pos.quantity = overrides.get("quantity", Decimal("0.1"))
    pos.stop_loss = overrides.get("stop_loss", Decimal("49000"))
    pos.take_profit = overrides.get("take_profit", Decimal("52000"))
    pos.unrealized_pnl = overrides.get("unrealized_pnl", Decimal("0"))
    pos.realized_pnl = overrides.get("realized_pnl", Decimal("0"))
    pos.execution_mode = overrides.get("execution_mode", ExecutionMode.PAPER.value)
    return pos


@pytest.mark.asyncio
async def test_stale_price_rejected():
    """Prices older than MAX_PRICE_STALE_SECONDS should return None."""
    mock_redis = AsyncMock()
    stale_ts = str(time.time() - MAX_PRICE_STALE_SECONDS - 5)
    mock_redis.hgetall.return_value = {
        "price": "50000.00",
        "timestamp": stale_ts,
    }

    with patch("app.tasks.position_monitor.get_redis", return_value=mock_redis):
        monitor = PositionMonitor(
            session_factory=AsyncMock(),
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis

        result = await monitor._get_price("BTCUSDT")

    assert result is None, "Stale price should be rejected (return None)"


@pytest.mark.asyncio
async def test_fresh_price_accepted():
    """Prices within MAX_PRICE_STALE_SECONDS should be accepted."""
    mock_redis = AsyncMock()
    fresh_ts = str(time.time() - 2)  # 2 seconds ago
    mock_redis.hgetall.return_value = {
        "price": "50123.45",
        "timestamp": fresh_ts,
    }

    with patch("app.tasks.position_monitor.get_redis", return_value=mock_redis):
        monitor = PositionMonitor(
            session_factory=AsyncMock(),
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis

        result = await monitor._get_price("BTCUSDT")

    assert result == Decimal("50123.45"), "Fresh price should be returned"


@pytest.mark.asyncio
async def test_dedup_prevents_double_close():
    """Second close on same position within TTL window should be skipped."""
    mock_redis = AsyncMock()
    # First call: nx=True succeeds (was_set = True)
    # Second call: nx=True fails (was_set = None/False)
    mock_redis.set.side_effect = [True, None]

    mock_session = AsyncMock()
    mock_pos_mgr = AsyncMock()
    mock_portfolio_svc = AsyncMock()

    trade = MagicMock()
    trade.pnl = Decimal("-50")
    mock_pos_mgr.close_position.return_value = trade

    position = _make_position()

    with patch("app.tasks.position_monitor.get_redis", return_value=mock_redis):
        monitor = PositionMonitor(
            session_factory=AsyncMock(),
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis

        # First close — should proceed
        with patch("app.core.notifications.notifier", new=AsyncMock()):
            await monitor._close_triggered(
                mock_session, mock_pos_mgr, mock_portfolio_svc,
                position, Decimal("49000"), "STOP_LOSS",
            )

        assert mock_pos_mgr.close_position.call_count == 1

        # Second close — should be deduplicated (skipped)
        mock_pos_mgr.close_position.reset_mock()

        await monitor._close_triggered(
            mock_session, mock_pos_mgr, mock_portfolio_svc,
            position, Decimal("49000"), "STOP_LOSS",
        )

        assert mock_pos_mgr.close_position.call_count == 0, \
            "Deduplicated close should NOT call close_position"


@pytest.mark.asyncio
async def test_execution_mode_from_position_not_monitor():
    """record_close should use ExecutionMode from the position, not the monitor's default."""
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True  # dedup passes

    mock_session = AsyncMock()
    mock_pos_mgr = AsyncMock()
    mock_portfolio_svc = AsyncMock()

    trade = MagicMock()
    trade.pnl = Decimal("100")
    mock_pos_mgr.close_position.return_value = trade

    # Position is LIVE, but monitor was created with PAPER default
    position = _make_position(execution_mode=ExecutionMode.LIVE.value)

    with patch("app.tasks.position_monitor.get_redis", return_value=mock_redis):
        monitor = PositionMonitor(
            session_factory=AsyncMock(),
            execution_mode=ExecutionMode.PAPER,  # monitor default
        )
        monitor._redis = mock_redis

        with patch("app.core.notifications.notifier", new=AsyncMock()):
            await monitor._close_triggered(
                mock_session, mock_pos_mgr, mock_portfolio_svc,
                position, Decimal("52000"), "TAKE_PROFIT",
            )

    # record_close should have been called with LIVE (from position),
    # not PAPER (from monitor)
    mock_portfolio_svc.record_close.assert_called_once()
    call_args = mock_portfolio_svc.record_close.call_args
    assert call_args[0][0] == ExecutionMode.LIVE, \
        "record_close must use execution_mode from the position"


# ── Exit Spread Validation ──


@pytest.mark.asyncio
async def test_exit_spread_too_wide_blocks_close():
    """If spread exceeds threshold, the close should be deferred."""
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True  # dedup passes
    # Wide spread: bid=50000, ask=51000 → 2% spread (exceeds 1% crypto max)
    mock_redis.hgetall.return_value = {
        "price": "50500",
        "bid": "50000",
        "ask": "51000",
        "timestamp": str(time.time()),
    }
    mock_redis.delete = AsyncMock()

    mock_session = AsyncMock()
    mock_pos_mgr = AsyncMock()
    mock_portfolio_svc = AsyncMock()

    position = _make_position()

    with patch("app.tasks.position_monitor.get_redis", return_value=mock_redis):
        monitor = PositionMonitor(
            session_factory=AsyncMock(),
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis

        await monitor._close_triggered(
            mock_session, mock_pos_mgr, mock_portfolio_svc,
            position, Decimal("49000"), "STOP_LOSS",
        )

    mock_pos_mgr.close_position.assert_not_called()
    # Dedup key should be released for retry on next cycle
    mock_redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_exit_spread_ok_allows_close():
    """If spread is within threshold, close should proceed."""
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True  # dedup passes
    # Tight spread: bid=50000, ask=50010 → 0.02% (well under 1%)
    mock_redis.hgetall.return_value = {
        "price": "50005",
        "bid": "50000",
        "ask": "50010",
        "timestamp": str(time.time()),
    }

    mock_session = AsyncMock()
    mock_pos_mgr = AsyncMock()
    mock_portfolio_svc = AsyncMock()

    trade = MagicMock()
    trade.pnl = Decimal("-50")
    mock_pos_mgr.close_position.return_value = trade

    position = _make_position()

    with patch("app.tasks.position_monitor.get_redis", return_value=mock_redis):
        monitor = PositionMonitor(
            session_factory=AsyncMock(),
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis

        with patch("app.core.notifications.notifier", new=AsyncMock()):
            await monitor._close_triggered(
                mock_session, mock_pos_mgr, mock_portfolio_svc,
                position, Decimal("49000"), "STOP_LOSS",
            )

    mock_pos_mgr.close_position.assert_called_once()


@pytest.mark.asyncio
async def test_market_close_skips_spread_check():
    """MARKET_CLOSE reason should always close, regardless of spread."""
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    # Wide spread (would normally block)
    mock_redis.hgetall.return_value = {
        "price": "50500",
        "bid": "50000",
        "ask": "51000",
        "timestamp": str(time.time()),
    }

    mock_session = AsyncMock()
    mock_pos_mgr = AsyncMock()
    mock_portfolio_svc = AsyncMock()

    trade = MagicMock()
    trade.pnl = Decimal("-100")
    mock_pos_mgr.close_position.return_value = trade

    position = _make_position()

    with patch("app.tasks.position_monitor.get_redis", return_value=mock_redis):
        monitor = PositionMonitor(
            session_factory=AsyncMock(),
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis

        with patch("app.core.notifications.notifier", new=AsyncMock()):
            await monitor._close_triggered(
                mock_session, mock_pos_mgr, mock_portfolio_svc,
                position, Decimal("49000"), "MARKET_CLOSE",
            )

    mock_pos_mgr.close_position.assert_called_once()


@pytest.mark.asyncio
async def test_exit_spread_no_bid_ask_allows_close():
    """If bid/ask data is missing, close should proceed (safety first)."""
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    mock_redis.hgetall.return_value = {
        "price": "50000",
        "timestamp": str(time.time()),
    }

    mock_session = AsyncMock()
    mock_pos_mgr = AsyncMock()
    mock_portfolio_svc = AsyncMock()

    trade = MagicMock()
    trade.pnl = Decimal("50")
    mock_pos_mgr.close_position.return_value = trade

    position = _make_position()

    with patch("app.tasks.position_monitor.get_redis", return_value=mock_redis):
        monitor = PositionMonitor(
            session_factory=AsyncMock(),
            execution_mode=ExecutionMode.PAPER,
        )
        monitor._redis = mock_redis

        with patch("app.core.notifications.notifier", new=AsyncMock()):
            await monitor._close_triggered(
                mock_session, mock_pos_mgr, mock_portfolio_svc,
                position, Decimal("52000"), "TAKE_PROFIT",
            )

    mock_pos_mgr.close_position.assert_called_once()
