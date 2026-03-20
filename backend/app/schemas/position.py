import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import PositionSide, PositionStatus


class PositionBase(BaseModel):
    symbol: str = Field(..., max_length=20)
    side: PositionSide = PositionSide.LONG
    entry_order_id: uuid.UUID
    entry_price: Decimal = Field(..., gt=0, decimal_places=8)
    current_price: Decimal = Field(..., gt=0, decimal_places=8)
    quantity: Decimal = Field(..., gt=0, decimal_places=8)
    stop_loss: Decimal = Field(..., gt=0, decimal_places=8)
    take_profit: Decimal = Field(..., gt=0, decimal_places=8)


class PositionCreate(PositionBase):
    opened_at: datetime


class PositionResponse(PositionBase):
    id: uuid.UUID
    status: PositionStatus
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    opened_at: datetime
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
