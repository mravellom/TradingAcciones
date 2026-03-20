from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StrategyConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "strategy_configs"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    strategy_type: Mapped[str] = mapped_column(String(50), nullable=False)  # momentum, mean_reversion, etc.

    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    symbols: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # ["BTCUSDT", "ETHUSDT"]
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, default="1h")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)

    __table_args__ = (
        Index("ix_strategy_configs_active", "is_active"),
    )
