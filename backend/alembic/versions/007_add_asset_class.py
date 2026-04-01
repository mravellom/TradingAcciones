"""Add asset_class column to signals, orders, positions, trades.

Revision ID: 007
Revises: 006
Create Date: 2026-04-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ["signals", "orders", "positions", "trades"]:
        op.add_column(
            table,
            sa.Column(
                "asset_class",
                sa.String(10),
                nullable=False,
                server_default="CRYPTO",
            ),
        )
        op.create_index(f"ix_{table}_asset_class", table, ["asset_class"])


def downgrade() -> None:
    for table in ["signals", "orders", "positions", "trades"]:
        op.drop_index(f"ix_{table}_asset_class", table_name=table)
        op.drop_column(table, "asset_class")
