from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.enums import (
    AggregateType,
    EventType,
    OrderSide,
    PositionStatus,
)
from app.domain.state_machine import validate_position_transition
from app.models.position import Position
from app.models.trade import Trade
from app.pipeline.execution.base import Fill
from app.repositories.event_repo import EventRepository
from app.repositories.position_repo import PositionRepository

logger = get_logger(__name__)


class PositionManager:
    """Manages position lifecycle: open, update, close, check SL/TP."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = PositionRepository(session)
        self._events = EventRepository(session)

    async def open_position(
        self,
        fill: Fill,
        stop_loss: Decimal,
        take_profit: Decimal,
        strategy_id: UUID,
        signal_confidence: Decimal,
        execution_mode: str = "PAPER",
        asset_class: str = "CRYPTO",
    ) -> Position:
        """Create a new position from a fill."""
        position = Position(
            symbol=fill.symbol,
            asset_class=asset_class,
            side="LONG",
            status=PositionStatus.OPEN.value,
            entry_order_id=fill.order_id,
            strategy_id=strategy_id,
            signal_confidence=signal_confidence,
            entry_price=fill.price,
            current_price=fill.price,
            quantity=fill.quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            execution_mode=execution_mode,
            opened_at=fill.timestamp,
        )
        await self._repo.create(position)

        await self._events.append(
            aggregate_type=AggregateType.POSITION,
            aggregate_id=position.id,
            event_type=EventType.POSITION_OPENED,
            event_data={
                "symbol": fill.symbol,
                "entry_price": str(fill.price),
                "quantity": str(fill.quantity),
                "stop_loss": str(stop_loss),
                "take_profit": str(take_profit),
                "order_id": str(fill.order_id),
            },
            metadata={"strategy_id": str(strategy_id)},
        )

        logger.info(
            "position_opened",
            position_id=str(position.id),
            symbol=fill.symbol,
            asset_class=asset_class,
            entry_price=str(fill.price),
            quantity=str(fill.quantity),
        )
        return position

    async def close_position(
        self,
        position_id: UUID,
        exit_price: Decimal,
        reason: str,
    ) -> Trade:
        """Close a position and create a trade record."""
        position = await self._repo.get_by_id(position_id)
        if position is None:
            raise ValueError(f"Position {position_id} not found")

        # Determine target status
        if reason == "STOP_LOSS":
            target_status = PositionStatus.STOPPED_OUT
            event_type = EventType.STOP_LOSS_TRIGGERED
        else:
            target_status = PositionStatus.CLOSED
            event_type = EventType.POSITION_CLOSED

        validate_position_transition(position.status, target_status)

        now = datetime.now(timezone.utc)

        # Calculate PnL
        pnl = (exit_price - position.entry_price) * position.quantity
        pnl_percent = (exit_price - position.entry_price) / position.entry_price
        duration = int((now - position.opened_at).total_seconds())

        # Update position
        position.status = target_status.value
        position.current_price = exit_price
        position.realized_pnl = pnl
        position.unrealized_pnl = Decimal("0")
        position.closed_at = now

        # Create trade record
        trade = Trade(
            position_id=position.id,
            symbol=position.symbol,
            asset_class=position.asset_class,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            pnl=pnl,
            pnl_percent=pnl_percent,
            signal_confidence=position.signal_confidence,
            strategy_id=position.strategy_id,
            execution_mode=position.execution_mode,
            duration_seconds=duration,
            opened_at=position.opened_at,
            closed_at=now,
        )
        self._session.add(trade)

        # Event
        await self._events.append(
            aggregate_type=AggregateType.POSITION,
            aggregate_id=position.id,
            event_type=event_type,
            event_data={
                "exit_price": str(exit_price),
                "pnl": str(pnl),
                "pnl_percent": str(pnl_percent),
                "reason": reason,
                "duration_seconds": duration,
            },
        )

        await self._session.flush()

        logger.info(
            "position_closed",
            position_id=str(position_id),
            reason=reason,
            pnl=str(pnl),
            pnl_percent=f"{pnl_percent:.4%}",
        )
        return trade

    async def update_price(self, position_id: UUID, current_price: Decimal) -> None:
        """Update a position's current price and unrealized PnL."""
        position = await self._repo.get_by_id(position_id)
        if position is None or position.status not in (
            PositionStatus.OPEN.value,
            PositionStatus.PARTIALLY_CLOSED.value,
        ):
            return

        position.current_price = current_price
        position.unrealized_pnl = (current_price - position.entry_price) * position.quantity
        await self._session.flush()

    async def check_stop_loss(self, position: Position, current_price: Decimal) -> bool:
        """Check if stop loss has been triggered."""
        if position.side == "LONG":
            return current_price <= position.stop_loss
        return False

    async def check_take_profit(self, position: Position, current_price: Decimal) -> bool:
        """Check if take profit has been triggered."""
        if position.side == "LONG":
            return current_price >= position.take_profit
        return False

    async def get_open_positions(self) -> list[Position]:
        return await self._repo.get_open()

    async def get_open_by_symbol(self, symbol: str) -> list[Position]:
        return await self._repo.get_open_by_symbol(symbol)
