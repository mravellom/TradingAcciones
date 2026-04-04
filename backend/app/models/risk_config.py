from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RiskConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "risk_configs"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, default="default")

    # Profile type
    profile_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="ULTRA_CONSERVADOR"
    )

    # Risk limits (global rules remain unchanged across profiles)
    max_daily_loss_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.03")
    )
    max_drawdown_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("0.10")
    )

    # Profile-specific parameters
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

    # Signal agreement
    allow_partial_signal_agreement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    min_agreeing_signals: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )

    # ATR-based SL/TP
    use_atr_for_sl_tp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    atr_period: Mapped[int] = mapped_column(
        Integer, nullable=False, default=14
    )
    atr_sl_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("1.5")
    )
    atr_tp_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("3.0")
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
