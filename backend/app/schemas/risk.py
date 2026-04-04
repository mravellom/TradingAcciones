import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import RiskProfileType


class RiskConfigResponse(BaseModel):
    id: uuid.UUID
    name: str
    profile_type: str
    max_daily_loss_pct: Decimal
    max_drawdown_pct: Decimal
    min_confidence: Decimal
    max_positions: int
    max_exposure_per_symbol_pct: Decimal
    risk_per_trade_pct: Decimal
    allow_partial_signal_agreement: bool
    min_agreeing_signals: int
    use_atr_for_sl_tp: bool
    atr_period: int
    atr_sl_multiplier: Decimal
    atr_tp_multiplier: Decimal
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
    active_profile: str = "ULTRA_CONSERVADOR"


class RiskProfileResponse(BaseModel):
    profile_type: str
    min_confidence: Decimal
    max_positions: int
    max_exposure_per_symbol_pct: Decimal
    risk_per_trade_pct: Decimal
    allow_partial_signal_agreement: bool
    min_agreeing_signals: int
    use_atr_for_sl_tp: bool
    atr_period: int
    atr_sl_multiplier: Decimal
    atr_tp_multiplier: Decimal
    # Global limits (read-only, same across profiles)
    max_daily_loss_pct: Decimal
    max_drawdown_pct: Decimal

    model_config = {"from_attributes": True}


class RiskProfileSwitch(BaseModel):
    profile_type: RiskProfileType


class RiskProfileHistoryEntry(BaseModel):
    previous_profile: str
    new_profile: str
    timestamp: datetime
    event_data: dict

    model_config = {"from_attributes": True}
