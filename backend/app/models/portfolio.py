from decimal import Decimal

from sqlalchemy import Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Portfolio(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "portfolios"

    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)  # PAPER/LIVE

    total_balance: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    available_balance: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    allocated_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("0")
    )

    total_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("0")
    )
    daily_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("0")
    )
    max_drawdown: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0")
    )

    __table_args__ = (
        Index("ix_portfolios_execution_mode", "execution_mode", unique=True),
    )
