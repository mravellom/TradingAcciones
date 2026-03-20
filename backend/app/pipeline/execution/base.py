from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.enums import ExecutionMode, OrderSide


@dataclass
class Fill:
    """Result of order execution."""

    order_id: UUID
    symbol: str
    side: OrderSide
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    execution_mode: ExecutionMode
    exchange_order_id: str = ""
    slippage: Decimal = Decimal("0")


class BaseExecutor(ABC):
    """Abstract executor interface.

    Paper and Binance executors share this same interface,
    guaranteeing paper testing exercises the same code path as live.
    """

    @property
    @abstractmethod
    def mode(self) -> ExecutionMode:
        """PAPER or LIVE."""

    @abstractmethod
    async def submit(
        self,
        order_id: UUID,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
    ) -> Fill:
        """Submit an order and return the fill."""

    @abstractmethod
    async def cancel(self, order_id: UUID, exchange_order_id: str = "") -> bool:
        """Cancel an open order. Returns True if successfully cancelled."""
