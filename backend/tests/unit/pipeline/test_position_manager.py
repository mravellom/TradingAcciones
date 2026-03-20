from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.enums import ExecutionMode, OrderSide, PositionStatus
from app.pipeline.execution.base import Fill
from app.pipeline.position_manager.position_manager import PositionManager


class TestPositionManagerLogic:
    """Test position manager logic that doesn't require DB."""

    def test_check_stop_loss_long_triggered(self):
        """SL triggered when price <= stop_loss for LONG."""
        from unittest.mock import MagicMock

        pos = MagicMock()
        pos.side = "LONG"
        pos.stop_loss = Decimal("41000")

        pm = PositionManager.__new__(PositionManager)

        import asyncio

        # Price at SL
        result = asyncio.get_event_loop().run_until_complete(
            pm.check_stop_loss(pos, Decimal("41000"))
        )
        assert result is True

        # Price below SL
        result = asyncio.get_event_loop().run_until_complete(
            pm.check_stop_loss(pos, Decimal("40500"))
        )
        assert result is True

        # Price above SL
        result = asyncio.get_event_loop().run_until_complete(
            pm.check_stop_loss(pos, Decimal("42000"))
        )
        assert result is False

    def test_check_take_profit_long_triggered(self):
        from unittest.mock import MagicMock

        pos = MagicMock()
        pos.side = "LONG"
        pos.take_profit = Decimal("44000")

        pm = PositionManager.__new__(PositionManager)

        import asyncio

        # Price at TP
        result = asyncio.get_event_loop().run_until_complete(
            pm.check_take_profit(pos, Decimal("44000"))
        )
        assert result is True

        # Price above TP
        result = asyncio.get_event_loop().run_until_complete(
            pm.check_take_profit(pos, Decimal("45000"))
        )
        assert result is True

        # Price below TP
        result = asyncio.get_event_loop().run_until_complete(
            pm.check_take_profit(pos, Decimal("43000"))
        )
        assert result is False
