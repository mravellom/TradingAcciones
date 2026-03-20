"""Fix available_balance constraint: >= 0, not >= -1

Revision ID: 004
Revises: 003
Create Date: 2026-03-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE portfolios DROP CONSTRAINT IF EXISTS ck_portfolio_available')
    op.execute(
        'ALTER TABLE portfolios ADD CONSTRAINT ck_portfolio_available CHECK (available_balance >= 0)'
    )


def downgrade() -> None:
    op.execute('ALTER TABLE portfolios DROP CONSTRAINT IF EXISTS ck_portfolio_available')
    op.execute(
        'ALTER TABLE portfolios ADD CONSTRAINT ck_portfolio_available CHECK (available_balance >= -1)'
    )
