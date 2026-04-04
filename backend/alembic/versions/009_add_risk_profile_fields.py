"""Add risk profile fields to risk_configs.

Revision ID: 009
Revises: 008
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "risk_configs",
        sa.Column("profile_type", sa.String(30), nullable=False, server_default="ULTRA_CONSERVADOR"),
    )
    op.add_column(
        "risk_configs",
        sa.Column("allow_partial_signal_agreement", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "risk_configs",
        sa.Column("min_agreeing_signals", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "risk_configs",
        sa.Column("use_atr_for_sl_tp", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "risk_configs",
        sa.Column("atr_period", sa.Integer(), nullable=False, server_default="14"),
    )
    op.add_column(
        "risk_configs",
        sa.Column("atr_sl_multiplier", sa.Numeric(8, 4), nullable=False, server_default="1.5"),
    )
    op.add_column(
        "risk_configs",
        sa.Column("atr_tp_multiplier", sa.Numeric(8, 4), nullable=False, server_default="3.0"),
    )


def downgrade() -> None:
    op.drop_column("risk_configs", "atr_tp_multiplier")
    op.drop_column("risk_configs", "atr_sl_multiplier")
    op.drop_column("risk_configs", "atr_period")
    op.drop_column("risk_configs", "use_atr_for_sl_tp")
    op.drop_column("risk_configs", "min_agreeing_signals")
    op.drop_column("risk_configs", "allow_partial_signal_agreement")
    op.drop_column("risk_configs", "profile_type")
