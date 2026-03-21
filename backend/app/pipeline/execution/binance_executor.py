"""Real Binance executor for spot trading.

Uses Binance Spot API (testnet or production).
Implements idempotency via newClientOrderId.
Includes retry with exponential backoff and post-failure reconciliation.
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from binance import AsyncClient
from binance.exceptions import BinanceAPIException

from app.config import settings
from app.core.logging import get_logger
from app.core.rate_limit import binance_rate_limiter
from app.core.retry import is_retryable_binance_error, retry_async
from app.domain.enums import ExecutionMode, OrderSide
from app.pipeline.execution.base import BaseExecutor, Fill

logger = get_logger(__name__)


class BinanceExecutor(BaseExecutor):
    """Real executor against Binance Spot API.

    - Uses testnet by default (settings.binance_testnet)
    - Idempotent via newClientOrderId (= internal order UUID)
    - Respects Binance rate limits
    - Retries transient failures with exponential backoff
    - Reconciles with Binance after timeout/errors
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
        """Submit a market order to Binance with retry and reconciliation."""
        await binance_rate_limiter.check()

        # Use order UUID as client order ID for idempotency
        client_order_id = f"TP-{order_id.hex[:20]}"

        try:
            result = await retry_async(
                self._create_order,
                symbol=symbol,
                side=side.value,
                quantity=str(quantity),
                client_order_id=client_order_id,
                max_retries=3,
                base_delay=1.0,
                max_delay=10.0,
                exceptions=(BinanceAPIException, asyncio.TimeoutError, ConnectionError, OSError),
                should_retry=is_retryable_binance_error,
            )
        except (BinanceAPIException, asyncio.TimeoutError, ConnectionError, OSError) as e:
            logger.error(
                "binance_order_failed_attempting_reconciliation",
                order_id=str(order_id),
                symbol=symbol,
                error=str(e),
            )
            # Attempt reconciliation: the order may have been accepted by Binance
            reconciled_fill = await self.reconcile_order(
                order_id=order_id,
                symbol=symbol,
                side=side,
                client_order_id=client_order_id,
                expected_price=price,
            )
            if reconciled_fill is not None:
                logger.info(
                    "binance_order_reconciled",
                    order_id=str(order_id),
                    exchange_order_id=reconciled_fill.exchange_order_id,
                )
                return reconciled_fill
            # Order truly doesn't exist on Binance
            raise

        return self._parse_fill(result, order_id, symbol, side, price, quantity)

    async def _create_order(
        self, *, symbol: str, side: str, quantity: str, client_order_id: str
    ) -> dict:
        """Create a market order on Binance. Separated for retry wrapper."""
        return await self.client.create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity,
            newClientOrderId=client_order_id,
        )

    async def reconcile_order(
        self,
        order_id: UUID,
        symbol: str,
        side: OrderSide,
        client_order_id: str,
        expected_price: Decimal,
    ) -> Fill | None:
        """Query Binance to check if an order was actually filled despite local error.

        Returns a Fill if the order exists and is filled, None otherwise.
        """
        try:
            result = await self.client.get_order(
                symbol=symbol,
                origClientOrderId=client_order_id,
            )
        except BinanceAPIException as e:
            if e.code == -2013:  # Order does not exist
                logger.info(
                    "reconcile_order_not_found",
                    order_id=str(order_id),
                    client_order_id=client_order_id,
                )
                return None
            logger.error(
                "reconcile_query_failed",
                order_id=str(order_id),
                code=e.code,
                message=e.message,
            )
            return None
        except Exception as e:
            logger.error("reconcile_query_error", order_id=str(order_id), error=str(e))
            return None

        status = result.get("status", "")
        if status not in ("FILLED", "PARTIALLY_FILLED"):
            logger.info(
                "reconcile_order_not_filled",
                order_id=str(order_id),
                status=status,
            )
            return None

        # Order exists and is filled — build Fill from Binance response
        executed_qty = Decimal(str(result.get("executedQty", "0")))
        cummulative_quote = Decimal(str(result.get("cummulativeQuoteQty", "0")))
        avg_price = (cummulative_quote / executed_qty) if executed_qty > 0 else expected_price

        return Fill(
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=avg_price.quantize(Decimal("0.00000001")),
            quantity=executed_qty.quantize(Decimal("0.00000001")),
            timestamp=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.LIVE,
            exchange_order_id=str(result.get("orderId", "")),
            slippage=abs(avg_price - expected_price).quantize(Decimal("0.00000001")),
        )

    async def place_oco_order(
        self,
        symbol: str,
        quantity: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal,
        client_order_id_prefix: str = "",
    ) -> str | None:
        """Place an OCO order on Binance for exchange-level SL/TP protection.

        Returns the OCO order list ID, or None if placement fails.
        """
        try:
            await binance_rate_limiter.check()
            result = await self.client.create_oco_order(
                symbol=symbol,
                side="SELL",  # Close long position
                quantity=str(quantity),
                price=str(take_profit),
                stopPrice=str(stop_loss),
                stopLimitPrice=str(stop_loss),
                stopLimitTimeInForce="GTC",
            )
            oco_id = str(result.get("orderListId", ""))
            logger.info(
                "oco_order_placed",
                symbol=symbol,
                oco_id=oco_id,
                stop_loss=str(stop_loss),
                take_profit=str(take_profit),
            )
            return oco_id
        except BinanceAPIException as e:
            logger.error(
                "oco_order_failed",
                symbol=symbol,
                code=e.code,
                message=e.message,
            )
            return None
        except Exception as e:
            logger.error("oco_order_error", symbol=symbol, error=str(e))
            return None

    def _parse_fill(
        self, result: dict, order_id: UUID, symbol: str,
        side: OrderSide, price: Decimal, quantity: Decimal,
    ) -> Fill:
        """Parse a Fill from Binance order response."""
        fills = result.get("fills", [])
        if fills:
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
