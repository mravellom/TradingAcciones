"""Alpaca executor for US stocks — paper mode initially, structured for live later."""

from decimal import Decimal
from uuid import UUID

from app.core.logging import get_logger
from app.domain.enums import ExecutionMode, OrderSide
from app.pipeline.execution.base import BaseExecutor, Fill
from app.pipeline.execution.paper_engine import PaperEngine

logger = get_logger(__name__)

# Stocks have tighter spreads than crypto
STOCK_SLIPPAGE_PCT = Decimal("0.0001")  # 0.01%


class AlpacaExecutor(BaseExecutor):
    """Alpaca executor — paper mode delegates to PaperEngine.

    The PaperEngine reads prices from Redis (price:{SYMBOL}), which are
    populated by AlpacaWebSocket. This means paper trading works automatically
    as long as the WS is feeding stock prices into Redis.
    """

    def __init__(self, paper_mode: bool = True):
        self._paper_mode = paper_mode
        self._paper_engine: PaperEngine | None = None
        if paper_mode:
            self._paper_engine = PaperEngine(
                slippage_pct=STOCK_SLIPPAGE_PCT,
                simulate_latency=True,
            )

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.PAPER if self._paper_mode else ExecutionMode.LIVE

    async def submit(
        self,
        order_id: UUID,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
    ) -> Fill:
        if self._paper_mode:
            return await self._paper_engine.submit(order_id, symbol, side, quantity, price)
        raise NotImplementedError("Live Alpaca execution not yet implemented")

    async def cancel(self, order_id: UUID, exchange_order_id: str = "") -> bool:
        if self._paper_mode:
            return await self._paper_engine.cancel(order_id, exchange_order_id)
        raise NotImplementedError("Live Alpaca cancellation not yet implemented")
