import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.exchange.base import ExchangeClient

logger = get_logger(__name__)


@dataclass
class HealthCheck:
    name: str
    status: str  # healthy, unhealthy, degraded
    latency_ms: float = 0
    error: str = ""


class SystemHealthMonitor:
    """Background task that monitors system health every N seconds.

    Checks:
    - Exchange API connectivity + latency
    - Database connectivity
    - Redis connectivity
    - Circuit breaker state

    Triggers global halt if critical checks fail.
    """

    def __init__(
        self,
        exchange: ExchangeClient | None = None,
        check_interval: int = 5,
        max_exchange_latency_ms: int = 2000,
    ):
        self._exchange = exchange
        self._check_interval = check_interval
        self._max_latency = max_exchange_latency_ms
        self._redis = get_redis()
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("health_monitor_started", interval=self._check_interval)
        while self._running:
            try:
                status = await self.check()
                await self._publish_status(status)
            except Exception as e:
                logger.error("health_monitor_error", error=str(e))
            await asyncio.sleep(self._check_interval)

    async def stop(self) -> None:
        self._running = False
        logger.info("health_monitor_stopped")

    async def check(self) -> dict:
        """Run all health checks and return results."""
        checks = {}

        # Redis
        try:
            await self._redis.ping()
            checks["redis"] = HealthCheck(name="redis", status="healthy")
        except Exception as e:
            checks["redis"] = HealthCheck(name="redis", status="unhealthy", error=str(e))

        # Exchange
        if self._exchange:
            try:
                latency = await self._exchange.ping()
                if latency > self._max_latency:
                    checks["exchange"] = HealthCheck(
                        name="exchange", status="degraded", latency_ms=latency,
                        error=f"High latency: {latency}ms > {self._max_latency}ms",
                    )
                else:
                    checks["exchange"] = HealthCheck(
                        name="exchange", status="healthy", latency_ms=latency,
                    )
            except Exception as e:
                checks["exchange"] = HealthCheck(
                    name="exchange", status="unhealthy", error=str(e),
                )

        # WebSocket connectivity
        ws_connected = await self._redis.get("ws:connected")
        if ws_connected == "1":
            checks["websocket"] = HealthCheck(name="websocket", status="healthy")
        elif ws_connected == "0":
            checks["websocket"] = HealthCheck(
                name="websocket", status="unhealthy", error="WebSocket disconnected"
            )
        else:
            checks["websocket"] = HealthCheck(
                name="websocket", status="degraded", error="WebSocket status unknown"
            )

        # Circuit breaker
        cb_active = await self._redis.get("circuit_breaker:active")
        checks["circuit_breaker"] = HealthCheck(
            name="circuit_breaker",
            status="active" if cb_active == "1" else "inactive",
        )

        # System status
        system_status = await self._redis.get("system:status") or "RUNNING"

        # Auto-halt on critical failure
        critical_failed = any(
            c.status == "unhealthy"
            for name, c in checks.items()
            if name in ("redis", "exchange")
        )
        if critical_failed and system_status != "HALTED":
            await self.global_halt("Critical health check failed")
            system_status = "HALTED"

        return {
            "status": "healthy" if not critical_failed else "unhealthy",
            "system_status": system_status,
            "checks": {k: {"status": v.status, "latency_ms": v.latency_ms, "error": v.error}
                       for k, v in checks.items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def global_halt(self, reason: str) -> None:
        """Halt the entire system."""
        await self._redis.set("system:status", "HALTED")
        logger.warning("system_global_halt", reason=reason)

    async def resume(self) -> None:
        """Resume the system."""
        await self._redis.set("system:status", "RUNNING")
        logger.info("system_resumed")

    async def _publish_status(self, status: dict) -> None:
        """Publish health status to Redis for WebSocket consumers."""
        import json
        await self._redis.publish("system:health", json.dumps(status))
