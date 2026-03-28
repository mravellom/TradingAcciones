"""Response models for analytics endpoints (OpenAPI documentation)."""
from pydantic import BaseModel


class AnalyticsSummary(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: str
    avg_pnl_per_trade: str
    sharpe_ratio: float | None = None
    max_drawdown: str | None = None

    class Config:
        extra = "allow"


class CumulativePnlItem(BaseModel):
    date: str
    pnl: str
    cumulative_pnl: str


class DrawdownItem(BaseModel):
    date: str
    drawdown: str
    drawdown_pct: str


class StrategyPerformanceItem(BaseModel):
    strategy_id: str
    strategy_name: str | None = None
    total_trades: int
    win_rate: float
    total_pnl: str

    class Config:
        extra = "allow"


class ExecutionModeStats(BaseModel):
    total_trades: int
    win_rate: float
    total_pnl: str
    avg_pnl: str

    class Config:
        extra = "allow"


class PaperVsLiveResponse(BaseModel):
    paper: ExecutionModeStats | None = None
    live: ExecutionModeStats | None = None


class MlShadowSymbolStats(BaseModel):
    count: int
    avg_confidence: float
    signals: list[dict]


class MlShadowResponse(BaseModel):
    total_shadow_signals: int | None = None
    by_symbol: dict[str, MlShadowSymbolStats] | None = None
    note: str | None = None
    status: str | None = None
    message: str | None = None
