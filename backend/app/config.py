from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_name: str = "Trading Platform"
    app_version: str = "0.1.0"
    debug: bool = False
    api_key: str = ""  # Empty = auth disabled (dev mode)

    # Secrets backend: "env" (default) or "docker-secrets"
    secrets_backend: str = "env"

    # CORS
    cors_origins: list[str] = ["http://localhost:4200"]

    @field_validator("cors_origins", "stock_symbols", mode="before")
    @classmethod
    def parse_comma_separated_list(cls, v):
        """Parse comma-separated list from env var."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # Rate limiting
    rate_limit_requests: int = 60  # requests per window
    rate_limit_window_seconds: int = 60  # window size

    # Database
    database_url: str = "postgresql+asyncpg://trading:trading_secret@localhost:5432/trading_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Binance
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True

    # Alpaca (US Stocks)
    alpaca_enabled: bool = False
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_data_url: str = "https://data.alpaca.markets"
    alpaca_ws_url: str = "wss://stream.data.alpaca.markets/v2/iex"
    stock_symbols: list[str] = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
        "TSLA", "META", "JPM", "V", "SPY",
    ]
    stock_scan_interval: int = 300  # 5 min

    # Execution
    execution_mode: str = "PAPER"  # PAPER | LIVE
    paper_initial_balance: float = 10000.0
    require_manual_approval: bool = False  # Human-in-the-loop mode
    approval_timeout_seconds: int = 300    # 5 min to approve before expiry

    # Notifications (Telegram)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Risk defaults
    risk_max_daily_loss_pct: float = 0.03       # 3%
    risk_max_drawdown_pct: float = 0.10          # 10%
    risk_min_confidence: float = 0.6
    risk_max_positions: int = 5
    risk_max_exposure_per_symbol_pct: float = 0.10  # 10%
    risk_per_trade_pct: float = 0.01             # 1%

    # Execution Guard (Crypto)
    guard_max_price_drift_pct: float = 0.005     # 0.5%
    guard_max_spread_pct: float = 0.003          # 0.3%
    guard_min_volume_24h: float = 100000.0       # USD

    # Execution Guard (Stocks)
    guard_stock_max_price_drift_pct: float = 0.002   # 0.2%
    guard_stock_max_spread_pct: float = 0.001         # 0.1%
    guard_stock_min_volume_24h: float = 1000000.0     # USD

    # Health monitor
    health_check_interval_seconds: int = 5
    health_max_exchange_latency_ms: int = 2000

    # ML
    model_max_age_days: int = 30

    @model_validator(mode="before")
    @classmethod
    def load_docker_secrets(cls, data: dict) -> dict:
        """Load secrets from Docker secrets files (/run/secrets/<name>)."""
        if data.get("secrets_backend", "env") != "docker-secrets":
            return data
        secret_fields = {
            "database_url": "database_url",
            "api_key": "api_key",
            "binance_api_key": "binance_api_key",
            "binance_api_secret": "binance_api_secret",
            "alpaca_api_key": "alpaca_api_key",
            "alpaca_api_secret": "alpaca_api_secret",
            "telegram_bot_token": "telegram_bot_token",
        }
        for secret_name, field_name in secret_fields.items():
            secret_path = Path(f"/run/secrets/{secret_name}")
            if secret_path.exists():
                data[field_name] = secret_path.read_text().strip()
        return data

    @model_validator(mode="after")
    def validate_live_mode(self) -> "Settings":
        """Fail fast if LIVE mode is misconfigured."""
        # Normalize execution_mode to uppercase for consistent comparison
        self.execution_mode = self.execution_mode.upper()
        if self.execution_mode == "LIVE":
            if not self.api_key:
                raise ValueError(
                    "API_KEY must be set when EXECUTION_MODE=LIVE. "
                    "Set API_KEY in your .env file."
                )
            if not self.binance_api_key or not self.binance_api_secret:
                raise ValueError(
                    "BINANCE_API_KEY and BINANCE_API_SECRET must be set when EXECUTION_MODE=LIVE."
                )
            if self.debug:
                raise ValueError(
                    "DEBUG must be False when EXECUTION_MODE=LIVE. "
                    "Never run LIVE mode with debug enabled."
                )
        return self


settings = Settings()
