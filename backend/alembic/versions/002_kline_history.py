"""Add kline_history table for ML training data

Revision ID: 002
Revises: 001
Create Date: 2026-03-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kline_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("interval", sa.String(10), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.Numeric(20, 8), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_kline_symbol_interval_time",
        "kline_history",
        ["symbol", "interval", "open_time"],
        unique=True,
    )
    op.create_index("ix_kline_open_time", "kline_history", ["open_time"])


def downgrade() -> None:
    op.drop_table("kline_history")
