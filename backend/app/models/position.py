import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Position(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "positions"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False, default="LONG")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")

    entry_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    signal_confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0")
    )
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    stop_loss: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    take_profit: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("0")
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("0")
    )

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_positions_symbol", "symbol"),
        Index("ix_positions_status", "status"),
        Index("ix_positions_opened_at", "opened_at"),
    )
