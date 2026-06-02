"""Backtest comparison: ULTRA_CONSERVADOR vs DEFENSIVO_AGRESIVO.

Simulates the same historical period with both risk profiles and generates
a side-by-side metrics report. Uses existing signal generators and evaluator.

Usage:
    python -m scripts.backtest_profiles
    python -m scripts.backtest_profiles --symbol BTCUSDT --timeframe 1h --days 180
"""
import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd

from app.core.logging import get_logger, setup_logging
from app.exchange.base import Kline
from app.ml.training.evaluator import TradingMetrics, evaluate_trades
from app.pipeline.signal_engine.atr import calculate_atr
from app.pipeline.signal_engine.composite import CompositeSignalGenerator
from app.pipeline.signal_engine.rsi import RSISignalGenerator
from app.pipeline.signal_engine.sma_crossover import SMACrossoverSignalGenerator

setup_logging()
logger = get_logger(__name__)


@dataclass
class ProfileConfig:
    name: str
    min_confidence: Decimal
    min_agreeing_signals: int | None  # None = unanimous
    use_atr: bool
    atr_sl_multiplier: Decimal
    atr_tp_multiplier: Decimal
    risk_per_trade: float


PROFILES = {
    "ULTRA_CONSERVADOR": ProfileConfig(
        name="ULTRA_CONSERVADOR",
        min_confidence=Decimal("0.60"),
        min_agreeing_signals=None,  # unanimous
        use_atr=False,
        atr_sl_multiplier=Decimal("1.5"),
        atr_tp_multiplier=Decimal("3.0"),
        risk_per_trade=0.01,
    ),
    "DEFENSIVO_AGRESIVO": ProfileConfig(
        name="DEFENSIVO_AGRESIVO",
        min_confidence=Decimal("0.55"),
        min_agreeing_signals=2,
        use_atr=True,
        atr_sl_multiplier=Decimal("1.5"),
        atr_tp_multiplier=Decimal("3.0"),
        risk_per_trade=0.015,
    ),
}


def _load_klines_from_db(symbol: str, timeframe: str, days: int) -> list[Kline]:
    """Load historical klines from the kline_history table."""
    import asyncio
    from sqlalchemy import select, text
    from app.core.database import async_session_factory
    from app.models.kline_history import KlineHistory

    async def _fetch():
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with async_session_factory() as session:
            stmt = (
                select(KlineHistory)
                .where(
                    KlineHistory.symbol == symbol,
                    KlineHistory.interval == timeframe,
                    KlineHistory.open_time >= since,
                )
                .order_by(KlineHistory.open_time)
            )
            result = await session.execute(stmt)
            rows = list(result.scalars().all())

        return [
            Kline(
                symbol=r.symbol,
                interval=r.interval,
                open_time=r.open_time,
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                volume=r.volume,
                close_time=r.close_time,
            )
            for r in rows
        ]

    return asyncio.get_event_loop().run_until_complete(_fetch())


def _simulate_profile(
    klines: list[Kline],
    profile: ProfileConfig,
    window: int = 100,
) -> pd.Series:
    """Simulate trading with a profile and return PnL series.

    Walks through klines with a sliding window, generates signals,
    and simulates trade outcomes using future prices.
    """
    import asyncio

    pnl_list = []

    for i in range(window, len(klines) - 1):
        window_klines = klines[i - window: i]

        # Create composite with profile params
        composite = CompositeSignalGenerator(
            generators=[
                (RSISignalGenerator(), 0.4),
                (SMACrossoverSignalGenerator(), 0.6),
            ],
            min_confidence=profile.min_confidence,
            min_agreeing_signals=profile.min_agreeing_signals,
        )

        signal = asyncio.get_event_loop().run_until_complete(
            composite.generate(klines[0].symbol, window_klines)
        )

        if signal is None:
            continue

        entry = float(signal.entry_price)
        next_close = float(klines[i].close)

        # Determine SL/TP
        if profile.use_atr:
            atr = calculate_atr(window_klines, period=14)
            if atr is None or atr == 0:
                continue
            atr_f = float(atr)
            sl_dist = atr_f * float(profile.atr_sl_multiplier)
            tp_dist = atr_f * float(profile.atr_tp_multiplier)
        else:
            sl_dist = entry * 0.02  # 2% fixed
            tp_dist = entry * 0.04  # 4% fixed

        # Simulate: check if next candle(s) hit SL or TP
        # Simple sim: look at the actual next candle
        high_next = float(klines[i].high)
        low_next = float(klines[i].low)

        if signal.signal_type.value == "BUY":
            sl_price = entry - sl_dist
            tp_price = entry + tp_dist
            if low_next <= sl_price:
                pnl_list.append(-sl_dist / entry)  # SL hit
            elif high_next >= tp_price:
                pnl_list.append(tp_dist / entry)  # TP hit
            else:
                pnl_list.append((next_close - entry) / entry)  # Hold
        else:
            sl_price = entry + sl_dist
            tp_price = entry - tp_dist
            if high_next >= sl_price:
                pnl_list.append(-sl_dist / entry)
            elif low_next <= tp_price:
                pnl_list.append(tp_dist / entry)
            else:
                pnl_list.append((entry - next_close) / entry)

    return pd.Series(pnl_list) if pnl_list else pd.Series(dtype=float)


def _print_report(
    symbol: str,
    timeframe: str,
    days: int,
    n_klines: int,
    results: dict[str, TradingMetrics],
):
    """Print formatted comparison report."""
    print("\n" + "=" * 70)
    print(f"  BACKTEST COMPARISON: {symbol} ({timeframe}, {days} days, {n_klines} candles)")
    print("=" * 70)

    header = f"{'Metric':<25} {'ULTRA_CONSERV':>15} {'DEFENSIVO_AGR':>15} {'Winner':>12}"
    print(header)
    print("-" * 70)

    u = results["ULTRA_CONSERVADOR"]
    d = results["DEFENSIVO_AGRESIVO"]

    rows = [
        ("Total Trades", u.total_trades, d.total_trades, "info"),
        ("Win Rate", f"{u.win_rate:.1%}", f"{d.win_rate:.1%}", "higher"),
        ("Profit Factor", f"{u.profit_factor:.2f}", f"{d.profit_factor:.2f}", "higher"),
        ("Expectancy", f"{u.expectancy:.4f}", f"{d.expectancy:.4f}", "higher"),
        ("Sharpe Ratio", f"{u.sharpe_ratio:.2f}", f"{d.sharpe_ratio:.2f}", "higher"),
        ("Sortino Ratio", f"{u.sortino_ratio:.2f}", f"{d.sortino_ratio:.2f}", "higher"),
        ("Max Drawdown", f"{u.max_drawdown:.2%}", f"{d.max_drawdown:.2%}", "lower"),
        ("Avg PnL/Trade", f"{u.avg_pnl:.4f}", f"{d.avg_pnl:.4f}", "higher"),
        ("Avg Win", f"{u.avg_win:.4f}", f"{d.avg_win:.4f}", "higher"),
        ("Avg Loss", f"{u.avg_loss:.4f}", f"{d.avg_loss:.4f}", "lower"),
        ("Best Trade", f"{u.best_trade:.4f}", f"{d.best_trade:.4f}", "higher"),
        ("Worst Trade", f"{u.worst_trade:.4f}", f"{d.worst_trade:.4f}", "higher"),
    ]

    for label, u_val, d_val, direction in rows:
        if direction == "info":
            winner = "-"
        elif direction == "higher":
            u_num = float(str(u_val).replace("%", "")) if isinstance(u_val, str) else u_val
            d_num = float(str(d_val).replace("%", "")) if isinstance(d_val, str) else d_val
            winner = "ULTRA" if u_num >= d_num else "DEFENS"
        elif direction == "lower":
            u_num = float(str(u_val).replace("%", "")) if isinstance(u_val, str) else u_val
            d_num = float(str(d_val).replace("%", "")) if isinstance(d_val, str) else d_val
            winner = "ULTRA" if u_num <= d_num else "DEFENS"
        else:
            winner = "-"

        print(f"{label:<25} {str(u_val):>15} {str(d_val):>15} {winner:>12}")

    print("-" * 70)

    # Overall verdict
    u_score = 0
    d_score = 0
    if u.profit_factor > d.profit_factor:
        u_score += 1
    else:
        d_score += 1
    if u.expectancy > d.expectancy:
        u_score += 1
    else:
        d_score += 1
    if u.sharpe_ratio > d.sharpe_ratio:
        u_score += 1
    else:
        d_score += 1
    if u.max_drawdown < d.max_drawdown:
        u_score += 1
    else:
        d_score += 1

    verdict = "ULTRA_CONSERVADOR" if u_score >= d_score else "DEFENSIVO_AGRESIVO"
    print(f"\n  Verdict: {verdict} wins {max(u_score, d_score)}-{min(u_score, d_score)} on key metrics")
    print(f"  (Based on: profit_factor, expectancy, sharpe, max_drawdown)\n")


def main():
    parser = argparse.ArgumentParser(description="Backtest risk profile comparison")
    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol to backtest")
    parser.add_argument("--timeframe", default="1h", help="Timeframe")
    parser.add_argument("--days", type=int, default=180, help="Days of history")
    args = parser.parse_args()

    print(f"Loading {args.symbol} {args.timeframe} data ({args.days} days)...")

    try:
        klines = _load_klines_from_db(args.symbol, args.timeframe, args.days)
    except Exception as e:
        print(f"Error loading from DB: {e}")
        print("Make sure you have historical data. Run: python -m scripts.download_data")
        return

    if len(klines) < 120:
        print(f"Insufficient data: {len(klines)} klines (need at least 120)")
        return

    print(f"Loaded {len(klines)} klines")

    results = {}
    for name, profile in PROFILES.items():
        print(f"Simulating {name}...")
        pnl_series = _simulate_profile(klines, profile)

        if len(pnl_series) == 0:
            print(f"  No trades generated for {name}")
            results[name] = TradingMetrics()
        else:
            metrics = evaluate_trades(pnl_series)
            results[name] = metrics
            print(f"  {metrics.summary()}")

    _print_report(args.symbol, args.timeframe, args.days, len(klines), results)


if __name__ == "__main__":
    main()
