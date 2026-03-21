"""Add oco_order_id and execution_mode to positions table.

Revision ID: 005
Revises: 004
Create Date: 2026-03-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column("execution_mode", sa.String(10), nullable=True),
    )
    op.add_column(
        "positions",
        sa.Column("oco_order_id", sa.String(100), nullable=True),
    )
    # Backfill existing positions
    op.execute("UPDATE positions SET execution_mode = 'PAPER' WHERE execution_mode IS NULL")
    # Now make it NOT NULL
    op.alter_column("positions", "execution_mode", nullable=False, server_default="PAPER")


def downgrade() -> None:
    op.drop_column("positions", "oco_order_id")
    op.drop_column("positions", "execution_mode")
