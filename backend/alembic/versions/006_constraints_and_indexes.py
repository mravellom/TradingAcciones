"""Add safety constraints and performance indexes.

Revision ID: 006
Revises: 005
Create Date: 2026-03-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === CONSTRAINTS ===

    # Portfolio: allocated cannot exceed total
    op.execute(
        "ALTER TABLE portfolios ADD CONSTRAINT ck_portfolio_allocated_lte_total "
        "CHECK (allocated_balance <= total_balance)"
    )

    # Positions: SL must be below entry for LONG positions
    op.execute(
        "ALTER TABLE positions ADD CONSTRAINT ck_position_long_sl_below_entry "
        "CHECK (side != 'LONG' OR stop_loss < entry_price)"
    )

    # Positions: TP must be above entry for LONG positions
    op.execute(
        "ALTER TABLE positions ADD CONSTRAINT ck_position_long_tp_above_entry "
        "CHECK (side != 'LONG' OR take_profit > entry_price)"
    )

    # Orders: filled quantity cannot exceed requested
    op.execute(
        "ALTER TABLE orders ADD CONSTRAINT ck_order_filled_lte_requested "
        "CHECK (filled_qty IS NULL OR filled_qty <= requested_qty)"
    )

    # === INDEXES ===

    # Composite index for exposure queries (symbol + status)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_positions_symbol_status "
        "ON positions (symbol, status)"
    )

    # Composite index for approval executor queries (status + created_at)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_status_created "
        "ON orders (status, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_status_created")
    op.execute("DROP INDEX IF EXISTS ix_positions_symbol_status")
    op.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_order_filled_lte_requested")
    op.execute("ALTER TABLE positions DROP CONSTRAINT IF EXISTS ck_position_long_tp_above_entry")
    op.execute("ALTER TABLE positions DROP CONSTRAINT IF EXISTS ck_position_long_sl_below_entry")
    op.execute("ALTER TABLE portfolios DROP CONSTRAINT IF EXISTS ck_portfolio_allocated_lte_total")
