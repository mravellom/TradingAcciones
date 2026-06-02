"""Add risk_profile_type to orders, positions, and trades.

Enables per-profile financial analytics by tagging every trade
with the risk profile that generated it.

Revision ID: 010
Revises: 009
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("risk_profile_type", sa.String(30), nullable=False, server_default="ULTRA_CONSERVADOR"),
    )
    op.add_column(
        "positions",
        sa.Column("risk_profile_type", sa.String(30), nullable=False, server_default="ULTRA_CONSERVADOR"),
    )
    op.add_column(
        "trades",
        sa.Column("risk_profile_type", sa.String(30), nullable=False, server_default="ULTRA_CONSERVADOR"),
    )
    # Index for analytics queries grouped by profile
    op.create_index("ix_trades_risk_profile", "trades", ["risk_profile_type"])


def downgrade() -> None:
    op.drop_index("ix_trades_risk_profile", table_name="trades")
    op.drop_column("trades", "risk_profile_type")
    op.drop_column("positions", "risk_profile_type")
    op.drop_column("orders", "risk_profile_type")
