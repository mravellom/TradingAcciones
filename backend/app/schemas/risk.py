import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class RiskConfigResponse(BaseModel):
    id: uuid.UUID
    name: str
    max_daily_loss_pct: Decimal
    max_drawdown_pct: Decimal
    min_confidence: Decimal
    max_positions: int
    max_exposure_per_symbol_pct: Decimal
    risk_per_trade_pct: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RiskConfigUpdate(BaseModel):
    max_daily_loss_pct: Decimal | None = Field(None, ge=0, le=1)
    max_drawdown_pct: Decimal | None = Field(None, ge=0, le=1)
    min_confidence: Decimal | None = Field(None, ge=0, le=1)
    max_positions: int | None = Field(None, ge=1)
    max_exposure_per_symbol_pct: Decimal | None = Field(None, ge=0, le=1)
    risk_per_trade_pct: Decimal | None = Field(None, ge=0, le=1)


class RiskStatusResponse(BaseModel):
    circuit_breaker_active: bool
    system_status: str
    daily_pnl: Decimal
    daily_loss_limit: Decimal
    open_positions: int
    max_positions: int
