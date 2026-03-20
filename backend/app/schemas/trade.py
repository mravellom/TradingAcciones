import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import ExecutionMode


class TradeResponse(BaseModel):
    id: uuid.UUID
    position_id: uuid.UUID
    symbol: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    pnl: Decimal
    pnl_percent: Decimal
    signal_confidence: Decimal
    strategy_id: uuid.UUID
    execution_mode: ExecutionMode
    duration_seconds: int
    opened_at: datetime
    closed_at: datetime

    model_config = {"from_attributes": True}
