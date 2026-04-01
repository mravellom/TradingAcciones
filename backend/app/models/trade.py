import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class Trade(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "trades"

    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_class: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'CRYPTO'")
    )

    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    pnl_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)

    signal_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_trades_symbol", "symbol"),
        Index("ix_trades_strategy", "strategy_id"),
        Index("ix_trades_closed_at", "closed_at"),
    )
