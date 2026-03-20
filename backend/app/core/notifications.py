"""Telegram notification service.

Sends alerts for:
- Order fills
- Stop loss / take profit triggers
- Circuit breaker activation
- System halt/resume
- Pending approvals (human-in-the-loop)
"""
import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramNotifier:
    """Sends trading alerts via Telegram Bot API."""

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ):
        self._token = bot_token or settings.telegram_bot_token
        self._chat_id = chat_id or settings.telegram_chat_id
        self._enabled = bool(self._token and self._chat_id)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured Telegram chat."""
        if not self._enabled:
            return False

        url = f"{TELEGRAM_API}/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": parse_mode,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    return True
                logger.warning(
                    "telegram_send_failed",
                    status=resp.status_code,
                    body=resp.text[:200],
                )
                return False
        except Exception as e:
            logger.error("telegram_error", error=str(e))
            return False

    # ── Convenience methods ──

    async def notify_fill(self, symbol: str, side: str, qty: str, price: str, pnl: str = "") -> None:
        pnl_line = f"\nP&L: <b>{pnl}</b>" if pnl else ""
        await self.send(
            f"<b>ORDER FILLED</b>\n"
            f"{side} {qty} {symbol} @ {price}{pnl_line}"
        )

    async def notify_stop_loss(self, symbol: str, entry: str, exit_price: str, pnl: str) -> None:
        await self.send(
            f"<b>STOP LOSS HIT</b>\n"
            f"{symbol}: entry {entry} -> exit {exit_price}\n"
            f"P&L: <b>{pnl}</b>"
        )

    async def notify_take_profit(self, symbol: str, entry: str, exit_price: str, pnl: str) -> None:
        await self.send(
            f"<b>TAKE PROFIT HIT</b>\n"
            f"{symbol}: entry {entry} -> exit {exit_price}\n"
            f"P&L: <b>{pnl}</b>"
        )

    async def notify_circuit_breaker(self, reason: str) -> None:
        await self.send(f"<b>CIRCUIT BREAKER ACTIVATED</b>\nReason: {reason}")

    async def notify_system_halt(self, reason: str) -> None:
        await self.send(f"<b>SYSTEM HALTED</b>\nReason: {reason}")

    async def notify_system_resume(self) -> None:
        await self.send("<b>SYSTEM RESUMED</b>\nTrading is active again.")

    async def notify_pending_approval(
        self, order_id: str, symbol: str, side: str, qty: str, price: str
    ) -> None:
        await self.send(
            f"<b>APPROVAL REQUIRED</b>\n"
            f"{side} {qty} {symbol} @ {price}\n"
            f"Order: <code>{order_id}</code>\n"
            f"Approve via dashboard or API."
        )

    async def notify_daily_summary(
        self, total_trades: int, pnl: str, win_rate: str, balance: str
    ) -> None:
        await self.send(
            f"<b>DAILY SUMMARY</b>\n"
            f"Trades: {total_trades}\n"
            f"P&L: <b>{pnl}</b>\n"
            f"Win Rate: {win_rate}\n"
            f"Balance: {balance}"
        )


# Singleton
notifier = TelegramNotifier()
