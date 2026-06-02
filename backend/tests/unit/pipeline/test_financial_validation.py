"""Tests for financial validation: advanced metrics, per-profile analytics, profile stamping."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.analytics_service import AnalyticsService


class FakeTrade:
    """Minimal trade object for testing _compute_advanced_metrics."""

    def __init__(self, pnl: float, pnl_pct: float, duration: int = 3600,
                 profile: str = "ULTRA_CONSERVADOR",
                 closed_at: datetime | None = None):
        self.pnl = Decimal(str(pnl))
        self.pnl_percent = Decimal(str(pnl_pct))
        self.duration_seconds = duration
        self.risk_profile_type = profile
        self.closed_at = closed_at or datetime.now(timezone.utc)
        self.symbol = "BTCUSDT"
        self.asset_class = "CRYPTO"


class TestAdvancedMetrics:
    def test_empty_trades_returns_zeros(self):
        result = AnalyticsService._compute_advanced_metrics([])
        assert result["total_trades"] == 0
        assert result["profit_factor"] == 0
        assert result["expectancy"] == 0

    def test_all_winning_trades(self):
        trades = [
            FakeTrade(pnl=100, pnl_pct=0.01),
            FakeTrade(pnl=200, pnl_pct=0.02),
            FakeTrade(pnl=150, pnl_pct=0.015),
        ]
        result = AnalyticsService._compute_advanced_metrics(trades)
        assert result["total_trades"] == 3
        assert result["wins"] == 3
        assert result["losses"] == 0
        assert result["win_rate"] == 1.0
        assert result["profit_factor"] == 999  # inf capped at 999
        assert result["max_drawdown"] == "0.0"

    def test_all_losing_trades(self):
        trades = [
            FakeTrade(pnl=-50, pnl_pct=-0.005),
            FakeTrade(pnl=-100, pnl_pct=-0.01),
        ]
        result = AnalyticsService._compute_advanced_metrics(trades)
        assert result["total_trades"] == 2
        assert result["wins"] == 0
        assert result["losses"] == 2
        assert result["win_rate"] == 0
        assert result["profit_factor"] == 0
        assert float(result["max_drawdown"]) > 0

    def test_mixed_trades_profit_factor(self):
        trades = [
            FakeTrade(pnl=200, pnl_pct=0.02),
            FakeTrade(pnl=-100, pnl_pct=-0.01),
            FakeTrade(pnl=150, pnl_pct=0.015),
            FakeTrade(pnl=-50, pnl_pct=-0.005),
        ]
        result = AnalyticsService._compute_advanced_metrics(trades)
        assert result["total_trades"] == 4
        assert result["wins"] == 2
        assert result["losses"] == 2
        # PF = (200 + 150) / (100 + 50) = 350/150 = 2.33
        assert result["profit_factor"] == 2.33

    def test_expectancy_positive_for_profitable_system(self):
        trades = [
            FakeTrade(pnl=300, pnl_pct=0.03),
            FakeTrade(pnl=-100, pnl_pct=-0.01),
            FakeTrade(pnl=200, pnl_pct=0.02),
            FakeTrade(pnl=-50, pnl_pct=-0.005),
        ]
        result = AnalyticsService._compute_advanced_metrics(trades)
        assert result["expectancy"] > 0

    def test_expectancy_negative_for_losing_system(self):
        trades = [
            FakeTrade(pnl=50, pnl_pct=0.005),
            FakeTrade(pnl=-200, pnl_pct=-0.02),
            FakeTrade(pnl=-150, pnl_pct=-0.015),
        ]
        result = AnalyticsService._compute_advanced_metrics(trades)
        assert result["expectancy"] < 0

    def test_max_drawdown_calculation(self):
        # Sequence: +100, +100, -300, +50
        # Cumulative: 100, 200, -100, -50
        # Peak:       100, 200, 200, 200
        # Drawdown:   0,   0,   300, 250
        trades = [
            FakeTrade(pnl=100, pnl_pct=0.01),
            FakeTrade(pnl=100, pnl_pct=0.01),
            FakeTrade(pnl=-300, pnl_pct=-0.03),
            FakeTrade(pnl=50, pnl_pct=0.005),
        ]
        result = AnalyticsService._compute_advanced_metrics(trades)
        assert float(result["max_drawdown"]) == 300.0

    def test_trades_per_day(self):
        from datetime import timedelta
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trades = [
            FakeTrade(pnl=10, pnl_pct=0.001, closed_at=base + timedelta(days=i))
            for i in range(10)
        ]
        result = AnalyticsService._compute_advanced_metrics(trades)
        # 10 trades over ~9 days span
        assert result["trades_per_day"] > 0

    def test_avg_hold_hours(self):
        trades = [
            FakeTrade(pnl=10, pnl_pct=0.001, duration=7200),  # 2h
            FakeTrade(pnl=20, pnl_pct=0.002, duration=3600),  # 1h
        ]
        result = AnalyticsService._compute_advanced_metrics(trades)
        assert result["avg_hold_hours"] == 1.5

    def test_best_worst_trade(self):
        trades = [
            FakeTrade(pnl=500, pnl_pct=0.05),
            FakeTrade(pnl=-200, pnl_pct=-0.02),
            FakeTrade(pnl=100, pnl_pct=0.01),
        ]
        result = AnalyticsService._compute_advanced_metrics(trades)
        assert float(result["best_trade"]) == 500.0
        assert float(result["worst_trade"]) == -200.0


class TestProfileStamping:
    def test_trade_model_has_risk_profile_type(self):
        """Verify the Trade model has the risk_profile_type field."""
        from app.models.trade import Trade
        assert hasattr(Trade, "risk_profile_type")

    def test_order_model_has_risk_profile_type(self):
        from app.models.order import Order
        assert hasattr(Order, "risk_profile_type")

    def test_position_model_has_risk_profile_type(self):
        from app.models.position import Position
        assert hasattr(Position, "risk_profile_type")
