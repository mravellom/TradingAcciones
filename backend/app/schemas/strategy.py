import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class StrategyConfigBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: str = ""
    strategy_type: str = Field(..., max_length=50)
    parameters: dict = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=list)
    timeframe: str = Field(default="1h", max_length=10)


class StrategyConfigCreate(StrategyConfigBase):
    pass


class StrategyConfigUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    parameters: dict | None = None
    symbols: list[str] | None = None
    timeframe: str | None = None
    is_active: bool | None = None


class StrategyConfigResponse(StrategyConfigBase):
    id: uuid.UUID
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
