"""Historical kline data for ML training and backtesting."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class KlineHistory(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "kline_history"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), nullable=False)

    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_kline_symbol_interval_time", "symbol", "interval", "open_time", unique=True),
        Index("ix_kline_open_time", "open_time"),
    )
