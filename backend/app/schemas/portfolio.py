import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.domain.enums import ExecutionMode


class PortfolioResponse(BaseModel):
    id: uuid.UUID
    execution_mode: ExecutionMode
    total_balance: Decimal
    available_balance: Decimal
    allocated_balance: Decimal
    total_pnl: Decimal
    daily_pnl: Decimal
    max_drawdown: Decimal
    updated_at: datetime

    model_config = {"from_attributes": True}
