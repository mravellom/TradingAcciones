class TradingPlatformError(Exception):
    """Base exception for the trading platform."""

    def __init__(self, message: str, code: str | None = None):
        self.message = message
        self.code = code
        super().__init__(self.message)


class RiskRejectedError(TradingPlatformError):
    """Raised when risk manager rejects a trade."""


class ExecutionGuardError(TradingPlatformError):
    """Raised when execution guard blocks a trade."""


class SystemHaltedError(TradingPlatformError):
    """Raised when the system is in HALTED state."""


class ExchangeError(TradingPlatformError):
    """Raised when exchange communication fails."""


class InvalidStateTransitionError(TradingPlatformError):
    """Raised when an invalid state machine transition is attempted."""
