"""Initial schema - all tables

Revision ID: 001
Revises: None
Create Date: 2026-03-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Events (event sourcing) ---
    op.create_table(
        "events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("event_data", JSONB, nullable=False, server_default="{}"),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("sequence_number", sa.BigInteger, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_events_aggregate", "events", ["aggregate_id", "sequence_number"], unique=True
    )
    op.create_index("ix_events_type", "events", ["event_type"])
    op.create_index("ix_events_created_at", "events", ["created_at"])

    # --- Strategy Configs ---
    op.create_table(
        "strategy_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("strategy_type", sa.String(50), nullable=False),
        sa.Column("parameters", JSONB, nullable=False, server_default="{}"),
        sa.Column("symbols", JSONB, nullable=False, server_default="[]"),
        sa.Column("timeframe", sa.String(10), nullable=False, server_default="1h"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_strategy_configs_active", "strategy_configs", ["is_active"])

    # --- Risk Configs ---
    op.create_table(
        "risk_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "max_daily_loss_pct", sa.Numeric(8, 4), nullable=False, server_default="0.03"
        ),
        sa.Column(
            "max_drawdown_pct", sa.Numeric(8, 4), nullable=False, server_default="0.10"
        ),
        sa.Column(
            "min_confidence", sa.Numeric(5, 4), nullable=False, server_default="0.6"
        ),
        sa.Column("max_positions", sa.Integer, nullable=False, server_default="5"),
        sa.Column(
            "max_exposure_per_symbol_pct",
            sa.Numeric(8, 4),
            nullable=False,
            server_default="0.10",
        ),
        sa.Column(
            "risk_per_trade_pct", sa.Numeric(8, 4), nullable=False, server_default="0.01"
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- Signals ---
    op.create_table(
        "signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("signal_type", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("indicators", JSONB, nullable=False, server_default="{}"),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("stop_loss", sa.Numeric(20, 8), nullable=False),
        sa.Column("take_profit", sa.Numeric(20, 8), nullable=False),
        sa.Column("strategy_id", UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_signals_symbol", "signals", ["symbol"])
    op.create_index("ix_signals_strategy", "signals", ["strategy_id"])
    op.create_index("ix_signals_created_at", "signals", ["created_at"])

    # --- Orders ---
    op.create_table(
        "orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("signal_id", UUID(as_uuid=True), sa.ForeignKey("signals.id"), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("order_type", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("requested_qty", sa.Numeric(20, 8), nullable=False),
        sa.Column("filled_qty", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("requested_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("avg_fill_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("stop_loss", sa.Numeric(20, 8), nullable=False),
        sa.Column("take_profit", sa.Numeric(20, 8), nullable=False),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("exchange_order_id", sa.String(100), nullable=True),
        sa.Column("risk_decision", JSONB, nullable=False, server_default="{}"),
        sa.Column("capital_decision", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_orders_signal", "orders", ["signal_id"])
    op.create_index("ix_orders_symbol", "orders", ["symbol"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])

    # --- Positions ---
    op.create_table(
        "positions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False, server_default="LONG"),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column(
            "entry_order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False
        ),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("current_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("stop_loss", sa.Numeric(20, 8), nullable=False),
        sa.Column("take_profit", sa.Numeric(20, 8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_positions_symbol", "positions", ["symbol"])
    op.create_index("ix_positions_status", "positions", ["status"])
    op.create_index("ix_positions_opened_at", "positions", ["opened_at"])

    # --- Trades (closed positions) ---
    op.create_table(
        "trades",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "position_id", UUID(as_uuid=True), sa.ForeignKey("positions.id"), nullable=False
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("pnl_percent", sa.Numeric(8, 4), nullable=False),
        sa.Column("signal_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("strategy_id", UUID(as_uuid=True), nullable=False),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trades_symbol", "trades", ["symbol"])
    op.create_index("ix_trades_strategy", "trades", ["strategy_id"])
    op.create_index("ix_trades_closed_at", "trades", ["closed_at"])

    # --- Portfolios ---
    op.create_table(
        "portfolios",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("total_balance", sa.Numeric(20, 8), nullable=False),
        sa.Column("available_balance", sa.Numeric(20, 8), nullable=False),
        sa.Column("allocated_balance", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("total_pnl", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("daily_pnl", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("max_drawdown", sa.Numeric(8, 4), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_portfolios_execution_mode", "portfolios", ["execution_mode"], unique=True
    )


def downgrade() -> None:
    op.drop_table("portfolios")
    op.drop_table("trades")
    op.drop_table("positions")
    op.drop_table("orders")
    op.drop_table("signals")
    op.drop_table("risk_configs")
    op.drop_table("strategy_configs")
    op.drop_table("events")
