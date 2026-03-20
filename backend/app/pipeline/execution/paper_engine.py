import asyncio
import random
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.enums import ExecutionMode, OrderSide
from app.pipeline.execution.base import BaseExecutor, Fill

logger = get_logger(__name__)

DEFAULT_SLIPPAGE_PCT = Decimal("0.0005")  # 0.05%
MIN_LATENCY_MS = 100
MAX_LATENCY_MS = 500


class PaperEngine(BaseExecutor):
    """Paper trading simulator.

    - Market orders fill at current price + simulated slippage
    - Simulates network latency (100-500ms)
    - Uses same interface as real executor
    """

    def __init__(
        self,
        slippage_pct: Decimal = DEFAULT_SLIPPAGE_PCT,
        simulate_latency: bool = True,
    ):
        self._slippage_pct = slippage_pct
        self._simulate_latency = simulate_latency
        self._redis = get_redis()

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.PAPER

    async def submit(
        self,
        order_id: UUID,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
    ) -> Fill:
        """Simulate order execution."""

        # Simulate network latency
        if self._simulate_latency:
            latency = random.randint(MIN_LATENCY_MS, MAX_LATENCY_MS)
            await asyncio.sleep(latency / 1000)

        # Get current price from cache or use order price
        current_price = await self._get_current_price(symbol, price)

        # Apply slippage
        slippage = current_price * self._slippage_pct
        if side == OrderSide.BUY:
            fill_price = current_price + slippage
        else:
            fill_price = current_price - slippage

        fill = Fill(
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=fill_price.quantize(Decimal("0.00000001")),
            quantity=quantity,
            timestamp=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.PAPER,
            exchange_order_id=f"PAPER-{uuid4().hex[:12]}",
            slippage=slippage.quantize(Decimal("0.00000001")),
        )

        logger.info(
            "paper_fill",
            order_id=str(order_id),
            symbol=symbol,
            side=side.value,
            price=str(fill.price),
            quantity=str(quantity),
            slippage=str(fill.slippage),
        )

        return fill

    async def cancel(self, order_id: UUID, exchange_order_id: str = "") -> bool:
        logger.info("paper_cancel", order_id=str(order_id))
        return True

    async def _get_current_price(self, symbol: str, fallback: Decimal) -> Decimal:
        """Get latest price from Redis cache, or use fallback."""
        cached = await self._redis.hgetall(f"price:{symbol}")
        if cached and "price" in cached:
            return Decimal(cached["price"])
        return fallback
