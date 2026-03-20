"""Add strategy_id to positions, CHECK constraints for financial safety

Revision ID: 003
Revises: 002
Create Date: 2026-03-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add strategy_id and signal_confidence to positions
    op.add_column(
        "positions",
        sa.Column("strategy_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "positions",
        sa.Column("signal_confidence", sa.Numeric(5, 4), nullable=True, server_default="0"),
    )

    # Backfill existing positions with a placeholder UUID
    op.execute(
        "UPDATE positions SET strategy_id = '00000000-0000-0000-0000-000000000000' WHERE strategy_id IS NULL"
    )
    op.execute(
        "UPDATE positions SET signal_confidence = 0 WHERE signal_confidence IS NULL"
    )

    # Make non-nullable after backfill
    op.alter_column("positions", "strategy_id", nullable=False)
    op.alter_column("positions", "signal_confidence", nullable=False)

    # CHECK constraints: prevent negative balances and invalid quantities
    op.execute(
        'ALTER TABLE portfolios ADD CONSTRAINT ck_portfolio_total_balance CHECK (total_balance >= 0)'
    )
    op.execute(
        'ALTER TABLE portfolios ADD CONSTRAINT ck_portfolio_available CHECK (available_balance >= -1)'
    )
    op.execute(
        'ALTER TABLE positions ADD CONSTRAINT ck_position_quantity CHECK (quantity > 0)'
    )
    op.execute(
        'ALTER TABLE positions ADD CONSTRAINT ck_position_entry_price CHECK (entry_price > 0)'
    )
    op.execute(
        'ALTER TABLE orders ADD CONSTRAINT ck_order_quantity CHECK (requested_qty > 0)'
    )


def downgrade() -> None:
    op.execute('ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_order_quantity')
    op.execute('ALTER TABLE positions DROP CONSTRAINT IF EXISTS ck_position_entry_price')
    op.execute('ALTER TABLE positions DROP CONSTRAINT IF EXISTS ck_position_quantity')
    op.execute('ALTER TABLE portfolios DROP CONSTRAINT IF EXISTS ck_portfolio_available')
    op.execute('ALTER TABLE portfolios DROP CONSTRAINT IF EXISTS ck_portfolio_total_balance')
    op.drop_column("positions", "signal_confidence")
    op.drop_column("positions", "strategy_id")
