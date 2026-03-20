"""Simulate a full trading session with realistic data.

Creates signals, orders, positions, trades, and events
to populate the dashboard with real-looking data.

Usage:
    python -m scripts.simulate_trades
"""
import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.config import settings
from app.core.database import async_session_factory
from app.domain.enums import (
    AggregateType,
    EventType,
    ExecutionMode,
    OrderStatus,
    PositionStatus,
)
from app.models.event_store import Event
from app.models.order import Order
from app.models.portfolio import Portfolio
from app.models.position import Position
from app.models.signal import Signal
from app.models.trade import Trade
from app.repositories.portfolio_repo import PortfolioRepository


# Simulation parameters
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
BASE_PRICES = {
    "BTCUSDT": 67500,
    "ETHUSDT": 3450,
    "SOLUSDT": 185,
    "BNBUSDT": 610,
}
NUM_CLOSED_TRADES = 25
NUM_OPEN_POSITIONS = 3
NUM_REJECTED_SIGNALS = 5


def random_price(base: float, pct_range: float = 0.05) -> Decimal:
    delta = base * random.uniform(-pct_range, pct_range)
    return Decimal(str(round(base + delta, 2)))


def random_confidence() -> Decimal:
    return Decimal(str(round(random.uniform(0.6, 0.92), 4)))


async def simulate():
    async with async_session_factory() as session:
        # Get strategy ID
        from sqlalchemy import select
        from app.models.strategy_config import StrategyConfig

        stmt = select(StrategyConfig).limit(1)
        result = await session.execute(stmt)
        strategy = result.scalar_one_or_none()
        if strategy is None:
            print("No strategy found. Run seed_paper_portfolio first.")
            return
        strategy_id = strategy.id

        # Get portfolio
        repo = PortfolioRepository(session)
        portfolio = await repo.get_by_mode(ExecutionMode.PAPER)
        if portfolio is None:
            print("No portfolio found. Run seed_paper_portfolio first.")
            return

        now = datetime.now(timezone.utc)
        total_pnl = Decimal("0")
        wins = 0
        losses = 0

        print(f"Simulating {NUM_CLOSED_TRADES} closed trades + {NUM_OPEN_POSITIONS} open positions...")
        print()

        # ── 1. Closed Trades (over the last 14 days) ──
        for i in range(NUM_CLOSED_TRADES):
            symbol = random.choice(SYMBOLS)
            base = BASE_PRICES[symbol]
            confidence = random_confidence()
            entry_price = random_price(base, 0.03)

            # 60% win rate
            is_win = random.random() < 0.60
            if is_win:
                exit_pct = random.uniform(0.005, 0.04)  # +0.5% to +4%
            else:
                exit_pct = random.uniform(-0.02, -0.005)  # -0.5% to -2%

            exit_price = entry_price * (Decimal("1") + Decimal(str(round(exit_pct, 4))))
            quantity = Decimal(str(round(random.uniform(50, 500) / float(entry_price), 6)))

            pnl = (exit_price - entry_price) * quantity
            pnl_percent = (exit_price - entry_price) / entry_price
            total_pnl += pnl

            if pnl > 0:
                wins += 1
            else:
                losses += 1

            # Random time in last 14 days
            days_ago = random.uniform(0.1, 14)
            opened_at = now - timedelta(days=days_ago)
            duration = random.randint(300, 86400)  # 5 min to 24 hours
            closed_at = opened_at + timedelta(seconds=duration)

            sl = entry_price * Decimal("0.98")
            tp = entry_price * Decimal("1.04")

            # Create signal
            signal = Signal(
                symbol=symbol,
                signal_type="BUY",
                confidence=confidence,
                timeframe="1h",
                indicators={
                    "rsi": round(random.uniform(20, 45), 1),
                    "sma_fast": float(entry_price * Decimal("0.99")),
                    "sma_slow": float(entry_price * Decimal("0.97")),
                },
                entry_price=entry_price,
                stop_loss=sl,
                take_profit=tp,
                strategy_id=strategy_id,
                expires_at=opened_at + timedelta(hours=1),
                created_at=opened_at,
                updated_at=opened_at,
            )
            session.add(signal)
            await session.flush()

            # Create order
            order = Order(
                signal_id=signal.id,
                symbol=symbol,
                side="BUY",
                order_type="MARKET",
                status=OrderStatus.FILLED.value,
                requested_qty=quantity,
                filled_qty=quantity,
                requested_price=entry_price,
                avg_fill_price=entry_price * (Decimal("1") + Decimal("0.0003")),
                stop_loss=sl,
                take_profit=tp,
                execution_mode=ExecutionMode.PAPER.value,
                exchange_order_id=f"PAPER-{uuid.uuid4().hex[:12]}",
                risk_decision={"action": "APPROVE", "rules_passed": 5},
                capital_decision={
                    "quantity": str(quantity),
                    "risk_amount": str(pnl.copy_abs()),
                    "position_value": str(entry_price * quantity),
                },
                created_at=opened_at,
                updated_at=closed_at,
            )
            session.add(order)
            await session.flush()

            # Create position (closed)
            reason = "TAKE_PROFIT" if pnl > 0 else "STOP_LOSS"
            pos_status = PositionStatus.CLOSED.value if pnl > 0 else PositionStatus.STOPPED_OUT.value

            position = Position(
                symbol=symbol,
                side="LONG",
                status=pos_status,
                entry_order_id=order.id,
                entry_price=entry_price,
                current_price=exit_price,
                quantity=quantity,
                stop_loss=sl,
                take_profit=tp,
                unrealized_pnl=Decimal("0"),
                realized_pnl=pnl,
                opened_at=opened_at,
                closed_at=closed_at,
            )
            session.add(position)
            await session.flush()

            # Create trade
            trade = Trade(
                position_id=position.id,
                symbol=symbol,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                pnl=pnl,
                pnl_percent=pnl_percent,
                signal_confidence=confidence,
                strategy_id=strategy_id,
                execution_mode=ExecutionMode.PAPER.value,
                duration_seconds=duration,
                opened_at=opened_at,
                closed_at=closed_at,
            )
            session.add(trade)

            # Event
            event = Event(
                aggregate_type=AggregateType.POSITION.value,
                aggregate_id=position.id,
                event_type=EventType.POSITION_CLOSED.value if pnl > 0 else EventType.STOP_LOSS_TRIGGERED.value,
                event_data={
                    "symbol": symbol,
                    "pnl": str(pnl),
                    "reason": reason,
                },
                metadata_={"correlation_id": uuid.uuid4().hex},
                sequence_number=1,
                created_at=closed_at,
            )
            session.add(event)

            status_icon = "+" if pnl > 0 else "-"
            print(f"  {status_icon} {symbol:10s} entry={entry_price:>10} exit={exit_price:>10} pnl={pnl:>10.2f} ({reason})")

        # ── 2. Open Positions ──
        print()
        print(f"Creating {NUM_OPEN_POSITIONS} open positions...")
        allocated = Decimal("0")

        for i in range(NUM_OPEN_POSITIONS):
            symbol = SYMBOLS[i % len(SYMBOLS)]
            base = BASE_PRICES[symbol]
            entry_price = random_price(base, 0.02)
            current_price = random_price(base, 0.03)
            quantity = Decimal(str(round(random.uniform(30, 300) / float(entry_price), 6)))
            confidence = random_confidence()

            sl = entry_price * Decimal("0.98")
            tp = entry_price * Decimal("1.04")
            unrealized = (current_price - entry_price) * quantity
            pos_value = entry_price * quantity
            allocated += pos_value

            opened_at = now - timedelta(hours=random.uniform(1, 48))

            signal = Signal(
                symbol=symbol,
                signal_type="BUY",
                confidence=confidence,
                timeframe="1h",
                indicators={"rsi": round(random.uniform(25, 40), 1)},
                entry_price=entry_price,
                stop_loss=sl,
                take_profit=tp,
                strategy_id=strategy_id,
                expires_at=opened_at + timedelta(hours=1),
                created_at=opened_at,
                updated_at=opened_at,
            )
            session.add(signal)
            await session.flush()

            order = Order(
                signal_id=signal.id,
                symbol=symbol,
                side="BUY",
                order_type="MARKET",
                status=OrderStatus.FILLED.value,
                requested_qty=quantity,
                filled_qty=quantity,
                requested_price=entry_price,
                avg_fill_price=entry_price,
                stop_loss=sl,
                take_profit=tp,
                execution_mode=ExecutionMode.PAPER.value,
                exchange_order_id=f"PAPER-{uuid.uuid4().hex[:12]}",
                risk_decision={"action": "APPROVE", "rules_passed": 5},
                capital_decision={"quantity": str(quantity)},
                created_at=opened_at,
                updated_at=opened_at,
            )
            session.add(order)
            await session.flush()

            position = Position(
                symbol=symbol,
                side="LONG",
                status=PositionStatus.OPEN.value,
                entry_order_id=order.id,
                entry_price=entry_price,
                current_price=current_price,
                quantity=quantity,
                stop_loss=sl,
                take_profit=tp,
                unrealized_pnl=unrealized,
                realized_pnl=Decimal("0"),
                opened_at=opened_at,
            )
            session.add(position)
            await session.flush()

            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            icon = "+" if unrealized > 0 else "-"
            print(f"  {icon} {symbol:10s} entry={entry_price:>10} current={current_price:>10} unrealized={unrealized:>10.2f} ({pnl_pct:.2f}%)")

        # ── 3. Rejected Signals (for variety) ──
        print()
        print(f"Creating {NUM_REJECTED_SIGNALS} rejected signals...")
        for i in range(NUM_REJECTED_SIGNALS):
            symbol = random.choice(SYMBOLS)
            base = BASE_PRICES[symbol]
            entry_price = random_price(base, 0.02)
            created_at = now - timedelta(hours=random.uniform(0.5, 72))

            signal = Signal(
                symbol=symbol,
                signal_type="BUY",
                confidence=Decimal(str(round(random.uniform(0.45, 0.59), 4))),
                timeframe="1h",
                indicators={"rsi": round(random.uniform(35, 50), 1)},
                entry_price=entry_price,
                stop_loss=entry_price * Decimal("0.97"),
                take_profit=entry_price * Decimal("1.05"),
                strategy_id=strategy_id,
                expires_at=created_at + timedelta(hours=1),
                created_at=created_at,
                updated_at=created_at,
            )
            session.add(signal)

            # Rejected order event
            event = Event(
                aggregate_type=AggregateType.ORDER.value,
                aggregate_id=uuid.uuid4(),
                event_type=EventType.RISK_REJECTED.value,
                event_data={
                    "rule": "min_confidence",
                    "reason": f"Confidence {signal.confidence} below minimum 0.6",
                },
                metadata_={"correlation_id": uuid.uuid4().hex},
                sequence_number=1,
                created_at=created_at,
            )
            session.add(event)
            print(f"  x {symbol:10s} confidence={signal.confidence} (REJECTED: min_confidence)")

        # ── 4. Update Portfolio ──
        portfolio.total_balance = Decimal("10000") + total_pnl
        portfolio.available_balance = portfolio.total_balance - allocated
        portfolio.allocated_balance = allocated
        portfolio.total_pnl = total_pnl
        portfolio.daily_pnl = total_pnl * Decimal("0.15")  # Approx today's portion
        if total_pnl < 0:
            portfolio.max_drawdown = abs(total_pnl) / Decimal("10000")
        else:
            portfolio.max_drawdown = Decimal("0.012")  # Small historical drawdown

        await session.commit()

        print()
        print("=" * 60)
        print(f"  Closed Trades:    {NUM_CLOSED_TRADES} ({wins}W / {losses}L)")
        print(f"  Win Rate:         {wins/NUM_CLOSED_TRADES*100:.1f}%")
        print(f"  Total PnL:        ${total_pnl:.2f}")
        print(f"  Open Positions:   {NUM_OPEN_POSITIONS}")
        print(f"  Allocated:        ${allocated:.2f}")
        print(f"  Portfolio:        ${portfolio.total_balance:.2f}")
        print(f"  Rejected Signals: {NUM_REJECTED_SIGNALS}")
        print("=" * 60)
        print("Simulation complete. Refresh your dashboard!")


if __name__ == "__main__":
    asyncio.run(simulate())
