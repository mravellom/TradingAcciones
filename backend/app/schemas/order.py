import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import ExecutionMode, OrderSide, OrderStatus, OrderType


class OrderBase(BaseModel):
    signal_id: uuid.UUID
    symbol: str = Field(..., max_length=20)
    side: OrderSide
    order_type: OrderType
    requested_qty: Decimal = Field(..., gt=0, decimal_places=8)
    requested_price: Decimal = Field(..., gt=0, decimal_places=8)
    stop_loss: Decimal = Field(..., gt=0, decimal_places=8)
    take_profit: Decimal = Field(..., gt=0, decimal_places=8)
    execution_mode: ExecutionMode


class OrderCreate(OrderBase):
    risk_decision: dict = Field(default_factory=dict)
    capital_decision: dict = Field(default_factory=dict)


class OrderResponse(OrderBase):
    id: uuid.UUID
    asset_class: str = "CRYPTO"
    status: OrderStatus
    filled_qty: Decimal
    avg_fill_price: Decimal | None = None
    exchange_order_id: str | None = None
    risk_decision: dict
    capital_decision: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    filled_qty: Decimal | None = None
    avg_fill_price: Decimal | None = None
    exchange_order_id: str | None = None
