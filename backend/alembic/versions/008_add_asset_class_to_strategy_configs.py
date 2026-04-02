"""Add asset_class column to strategy_configs.

Revision ID: 008
Revises: 007
Create Date: 2026-04-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "strategy_configs",
        sa.Column("asset_class", sa.String(10), nullable=False, server_default="CRYPTO"),
    )
    op.create_index("ix_strategy_configs_asset_class", "strategy_configs", ["asset_class"])


def downgrade() -> None:
    op.drop_index("ix_strategy_configs_asset_class", table_name="strategy_configs")
    op.drop_column("strategy_configs", "asset_class")
