"""Real Binance executor for spot trading.

Uses Binance Spot API (testnet or production).
Implements idempotency via newClientOrderId.
"""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from binance import AsyncClient
from binance.exceptions import BinanceAPIException

from app.config import settings
from app.core.logging import get_logger
from app.core.rate_limit import binance_rate_limiter
from app.domain.enums import ExecutionMode, OrderSide
from app.pipeline.execution.base import BaseExecutor, Fill

logger = get_logger(__name__)


class BinanceExecutor(BaseExecutor):
    """Real executor against Binance Spot API.

    - Uses testnet by default (settings.binance_testnet)
    - Idempotent via newClientOrderId (= internal order UUID)
    - Respects Binance rate limits
    """

    def __init__(self):
        self._client: AsyncClient | None = None

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.LIVE

    async def connect(self) -> None:
        if self._client is not None:
            return
        self._client = await AsyncClient.create(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            testnet=settings.binance_testnet,
        )
        logger.info("binance_executor_connected", testnet=settings.binance_testnet)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close_connection()
            self._client = None

    @property
    def client(self) -> AsyncClient:
        if self._client is None:
            raise RuntimeError("BinanceExecutor not connected")
        return self._client

    async def submit(
        self,
        order_id: UUID,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
    ) -> Fill:
        """Submit a market order to Binance."""
        await binance_rate_limiter.check()

        # Use order UUID as client order ID for idempotency
        client_order_id = f"TP-{order_id.hex[:20]}"

        try:
            result = await self.client.create_order(
                symbol=symbol,
                side=side.value,
                type="MARKET",
                quantity=str(quantity),
                newClientOrderId=client_order_id,
            )
        except BinanceAPIException as e:
            logger.error(
                "binance_order_failed",
                order_id=str(order_id),
                symbol=symbol,
                code=e.code,
                message=e.message,
            )
            raise

        # Parse fill from response
        fills = result.get("fills", [])
        if fills:
            # Weighted average fill price
            total_qty = Decimal("0")
            total_cost = Decimal("0")
            for f in fills:
                qty = Decimal(f["qty"])
                px = Decimal(f["price"])
                total_qty += qty
                total_cost += qty * px
            avg_price = total_cost / total_qty if total_qty > 0 else price
        else:
            avg_price = Decimal(str(result.get("price", price)))
            total_qty = Decimal(str(result.get("executedQty", quantity)))

        slippage = abs(avg_price - price)

        fill = Fill(
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=avg_price.quantize(Decimal("0.00000001")),
            quantity=total_qty.quantize(Decimal("0.00000001")),
            timestamp=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.LIVE,
            exchange_order_id=str(result.get("orderId", "")),
            slippage=slippage.quantize(Decimal("0.00000001")),
        )

        logger.info(
            "binance_order_filled",
            order_id=str(order_id),
            exchange_order_id=fill.exchange_order_id,
            symbol=symbol,
            side=side.value,
            price=str(fill.price),
            quantity=str(fill.quantity),
            slippage=str(fill.slippage),
        )

        return fill

    async def cancel(
        self, order_id: UUID, exchange_order_id: str = "", symbol: str = ""
    ) -> bool:
        """Cancel an open order on Binance. Requires symbol and exchange_order_id."""
        if not exchange_order_id:
            logger.warning("binance_cancel_no_exchange_id", order_id=str(order_id))
            return False
        if not symbol:
            logger.warning("binance_cancel_no_symbol", order_id=str(order_id))
            return False

        try:
            await binance_rate_limiter.check()
            await self.client.cancel_order(
                symbol=symbol,
                orderId=exchange_order_id,
            )
            logger.info(
                "binance_order_cancelled",
                symbol=symbol,
                exchange_order_id=exchange_order_id,
            )
            return True
        except BinanceAPIException as e:
            logger.error(
                "binance_cancel_failed",
                exchange_order_id=exchange_order_id,
                code=e.code,
                message=e.message,
            )
            return False
