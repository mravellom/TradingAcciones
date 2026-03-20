"""Trading-specific evaluation metrics.

NOT accuracy. NOT F1. These are financial metrics that matter.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class TradingMetrics:
    """All metrics that matter for evaluating a trading model."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    profit_factor: float = 0.0        # sum(wins) / sum(losses). >1.5 = good
    sharpe_ratio: float = 0.0         # >1.5 = good, >2.0 = excellent
    sortino_ratio: float = 0.0        # Like Sharpe but only penalizes downside
    max_drawdown: float = 0.0         # <10% = acceptable
    calmar_ratio: float = 0.0         # annual_return / max_drawdown
    expectancy: float = 0.0           # (wr * avg_win) - (lr * avg_loss). >0 = profitable
    avg_win: float = 0.0
    avg_loss: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0

    @property
    def is_profitable(self) -> bool:
        return self.expectancy > 0 and self.profit_factor > 1.0

    def summary(self) -> str:
        return (
            f"Trades={self.total_trades} WR={self.win_rate:.1%} "
            f"PF={self.profit_factor:.2f} Sharpe={self.sharpe_ratio:.2f} "
            f"DD={self.max_drawdown:.2%} Expect={self.expectancy:.4f}"
        )


def evaluate_trades(
    pnl_series: pd.Series,
    tp_pct: float = 0.015,
    sl_pct: float = 0.01,
    annual_periods: int = 8760,  # hours in a year (for 1h data)
) -> TradingMetrics:
    """Evaluate trading performance from a series of PnL per trade.

    Args:
        pnl_series: Series of PnL percentages per trade.
        tp_pct: Take profit % (for expectancy calculation).
        sl_pct: Stop loss % (for expectancy calculation).
        annual_periods: Periods per year for annualization.
    """
    if len(pnl_series) == 0:
        return TradingMetrics()

    wins_mask = pnl_series > 0
    losses_mask = pnl_series <= 0

    total = len(pnl_series)
    wins = wins_mask.sum()
    losses = losses_mask.sum()
    win_rate = wins / total if total > 0 else 0

    total_pnl = pnl_series.sum()
    avg_pnl = pnl_series.mean()

    gross_profit = pnl_series[wins_mask].sum() if wins > 0 else 0
    gross_loss = abs(pnl_series[losses_mask].sum()) if losses > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win = pnl_series[wins_mask].mean() if wins > 0 else 0
    avg_loss = abs(pnl_series[losses_mask].mean()) if losses > 0 else 0

    # Expectancy: average expected return per trade
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    # Sharpe Ratio (annualized)
    if pnl_series.std() > 0:
        sharpe = (pnl_series.mean() / pnl_series.std()) * np.sqrt(annual_periods / max(total, 1))
    else:
        sharpe = 0.0

    # Sortino Ratio (only penalizes downside volatility)
    downside = pnl_series[pnl_series < 0]
    downside_std = downside.std() if len(downside) > 1 else 0
    if downside_std > 0:
        sortino = (pnl_series.mean() / downside_std) * np.sqrt(annual_periods / max(total, 1))
    else:
        sortino = 0.0

    # Max Drawdown
    cumulative = pnl_series.cumsum()
    peak = cumulative.expanding().max()
    drawdown = (cumulative - peak)
    max_dd = abs(drawdown.min()) if len(drawdown) > 0 else 0

    # Calmar Ratio
    annual_return = total_pnl * (annual_periods / max(total, 1))
    calmar = annual_return / max_dd if max_dd > 0 else 0.0

    return TradingMetrics(
        total_trades=total,
        wins=int(wins),
        losses=int(losses),
        win_rate=float(win_rate),
        total_pnl=float(total_pnl),
        avg_pnl=float(avg_pnl),
        profit_factor=float(min(profit_factor, 999)),
        sharpe_ratio=float(sharpe),
        sortino_ratio=float(sortino),
        max_drawdown=float(max_dd),
        calmar_ratio=float(min(calmar, 999)),
        expectancy=float(expectancy),
        avg_win=float(avg_win),
        avg_loss=float(avg_loss),
        best_trade=float(pnl_series.max()),
        worst_trade=float(pnl_series.min()),
    )


def evaluate_predictions(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    tp_pct: float = 0.015,
    sl_pct: float = 0.01,
    min_probability: float = 0.5,
) -> TradingMetrics:
    """Evaluate ML predictions as if they were traded.

    Simulates: if model predicts 1 (and probability >= threshold), take the trade.
    The trade's PnL depends on whether the label was actually 1 (TP hit) or 0 (SL hit).
    """
    # Only trade when model says yes
    trade_mask = y_pred >= min_probability

    if trade_mask.sum() == 0:
        return TradingMetrics()

    # For each trade: win = +tp_pct, lose = -sl_pct
    traded_labels = y_true[trade_mask]
    pnl_per_trade = pd.Series(
        np.where(traded_labels == 1, tp_pct, -sl_pct)
    )

    metrics = evaluate_trades(pnl_per_trade, tp_pct, sl_pct)
    return metrics
