import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Order(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "orders"

    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_class: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'CRYPTO'")
    )
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY/SELL
    order_type: Mapped[str] = mapped_column(String(10), nullable=False)  # MARKET/LIMIT
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")

    requested_qty: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    filled_qty: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("0")
    )
    requested_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    stop_loss: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    take_profit: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)  # PAPER/LIVE
    exchange_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    risk_profile_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'ULTRA_CONSERVADOR'")
    )

    risk_decision: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    capital_decision: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_orders_signal", "signal_id"),
        Index("ix_orders_symbol", "symbol"),
        Index("ix_orders_status", "status"),
        Index("ix_orders_created_at", "created_at"),
    )
