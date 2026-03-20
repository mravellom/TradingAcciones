import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import SignalType


class SignalBase(BaseModel):
    symbol: str = Field(..., max_length=20, examples=["BTCUSDT"])
    signal_type: SignalType
    confidence: Decimal = Field(..., ge=0, le=1, decimal_places=4)
    timeframe: str = Field(..., max_length=10, examples=["1h"])
    indicators: dict = Field(default_factory=dict)
    entry_price: Decimal = Field(..., gt=0, decimal_places=8)
    stop_loss: Decimal = Field(..., gt=0, decimal_places=8)
    take_profit: Decimal = Field(..., gt=0, decimal_places=8)
    strategy_id: uuid.UUID
    expires_at: datetime


class SignalCreate(SignalBase):
    pass


class SignalResponse(SignalBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
