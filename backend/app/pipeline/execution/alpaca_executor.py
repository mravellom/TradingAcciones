"""Alpaca executor for US stocks — paper and live modes."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.config import settings
from app.core.logging import get_logger
from app.domain.enums import ExecutionMode, OrderSide
from app.exchange.market_hours import is_us_market_open
from app.pipeline.execution.base import BaseExecutor, Fill
from app.pipeline.execution.paper_engine import PaperEngine

logger = get_logger(__name__)

STOCK_SLIPPAGE_PCT = Decimal("0.0001")  # 0.01%
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0


class AlpacaExecutor(BaseExecutor):
    """Alpaca executor — paper mode delegates to PaperEngine,
    live mode submits real LIMIT orders via Alpaca Trading API.
    """

    def __init__(self, paper_mode: bool = True):
        self._paper_mode = paper_mode
        self._paper_engine: PaperEngine | None = None
        self._trading_client = None

        if paper_mode:
            self._paper_engine = PaperEngine(
                slippage_pct=STOCK_SLIPPAGE_PCT,
                simulate_latency=True,
            )

    async def connect(self) -> None:
        """Initialize Alpaca Trading Client for live mode."""
        if self._paper_mode:
            return
        from alpaca.trading.client import TradingClient
        self._trading_client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_api_secret,
            paper=True,  # Use paper endpoint even in "live" mode for safety
        )
        logger.info("alpaca_executor_connected")

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
        return await self._submit_live(order_id, symbol, side, quantity, price)

    async def cancel(self, order_id: UUID, exchange_order_id: str = "") -> bool:
        if self._paper_mode:
            return await self._paper_engine.cancel(order_id, exchange_order_id)
        return await self._cancel_live(exchange_order_id)

    async def _submit_live(
        self,
        order_id: UUID,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
    ) -> Fill:
        """Submit a real LIMIT order via Alpaca."""
        if not is_us_market_open():
            raise RuntimeError(f"Cannot submit order for {symbol}: US market is closed")

        if self._trading_client is None:
            raise RuntimeError("AlpacaExecutor not connected. Call connect() first.")

        from alpaca.trading.requests import LimitOrderRequest
        from alpaca.trading.enums import OrderSide as AlpacaSide, TimeInForce

        # Use LIMIT order with tight band around current price (safer than MARKET)
        limit_spread = Decimal("0.005")  # 0.5% band
        if side == OrderSide.BUY:
            limit_price = price * (Decimal("1") + limit_spread)
        else:
            limit_price = price * (Decimal("1") - limit_spread)

        alpaca_side = AlpacaSide.BUY if side == OrderSide.BUY else AlpacaSide.SELL

        request = LimitOrderRequest(
            symbol=symbol,
            qty=float(quantity),
            side=alpaca_side,
            time_in_force=TimeInForce.DAY,
            limit_price=float(limit_price.quantize(Decimal("0.01"))),
            client_order_id=str(order_id),
        )

        logger.info(
            "alpaca_order_submitting",
            order_id=str(order_id),
            symbol=symbol,
            side=side.value,
            qty=str(quantity),
            limit_price=str(limit_price),
        )

        # Submit with retry
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                order = self._trading_client.submit_order(request)
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    "alpaca_order_retry",
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        else:
            raise RuntimeError(f"Alpaca order failed after {MAX_RETRIES} retries: {last_error}")

        # Wait for fill (poll status)
        fill_price = price
        fill_qty = quantity
        exchange_order_id = order.id

        # Poll for fill (max 30s)
        for _ in range(30):
            await asyncio.sleep(1)
            updated = self._trading_client.get_order_by_id(order.id)
            if updated.status in ("filled", "partially_filled"):
                fill_price = Decimal(str(updated.filled_avg_price or price))
                fill_qty = Decimal(str(updated.filled_qty or quantity))
                break
            if updated.status in ("cancelled", "expired", "rejected"):
                raise RuntimeError(f"Alpaca order {updated.status}: {symbol} {side.value}")

        slippage = abs(fill_price - price)

        fill = Fill(
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=fill_price,
            quantity=fill_qty,
            timestamp=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.LIVE,
            exchange_order_id=str(exchange_order_id),
            slippage=slippage,
        )

        logger.info(
            "alpaca_order_filled",
            order_id=str(order_id),
            symbol=symbol,
            fill_price=str(fill_price),
            fill_qty=str(fill_qty),
            slippage=str(slippage),
        )

        return fill

    async def _cancel_live(self, exchange_order_id: str) -> bool:
        """Cancel an open order on Alpaca."""
        if self._trading_client is None:
            return False
        try:
            self._trading_client.cancel_order_by_id(exchange_order_id)
            logger.info("alpaca_order_cancelled", exchange_order_id=exchange_order_id)
            return True
        except Exception as e:
            logger.error("alpaca_cancel_failed", exchange_order_id=exchange_order_id, error=str(e))
            return False
