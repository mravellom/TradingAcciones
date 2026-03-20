from decimal import Decimal

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RiskConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "risk_configs"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, default="default")

    max_daily_loss_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.03")
    )
    max_drawdown_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.10")
    )
    min_confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.6")
    )
    max_positions: Mapped[int] = mapped_column(nullable=False, default=5)
    max_exposure_per_symbol_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.10")
    )
    risk_per_trade_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.01")
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
