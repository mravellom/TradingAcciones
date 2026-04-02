# TradingAcciones

Plataforma de trading algoritmico para **criptomonedas (Binance)** y **acciones USA — S&P 500, NASDAQ (Alpaca)**. Ambos mercados corren simultaneamente.

## Stack

- **Backend:** Python 3.11 + FastAPI (async)
- **Frontend:** Angular 20 + TypeScript
- **DB:** PostgreSQL 16
- **Cache:** Redis 7
- **Crypto:** Binance API (REST + WebSocket, 24/7)
- **Stocks:** Alpaca API (REST + WebSocket, Lun-Vie 9:30-16:00 ET)
- **ML:** XGBoost + pandas + pandas-ta
- **Infra:** Docker Compose

## Features

- Senales tecnicas: RSI, SMA crossover, ML (XGBoost 40+ features)
- Estrategias: MomentumStrategy (crypto), StockMomentumStrategy (acciones)
- 5 reglas de riesgo: min confidence, daily loss, max drawdown, max positions, max exposure
- Execution Guard con thresholds diferenciados crypto vs stocks
- Paper trading + live trading (Binance y Alpaca)
- Auto-cierre de posiciones stock a las 3:55 PM ET
- Horario de mercado USA con festivos (via Alpaca calendar API)
- Circuit breaker automatico
- Reconciliacion startup + runtime (LIVE mode)
- Dashboard Angular con badges CRY/STK y estado mercado USA
- ML shadow scanner para evaluar predicciones sin ejecutar
- Backtesting walk-forward con XGBoost

## Quick Start

```bash
# 1. Levantar DB y Redis
cd backend
docker compose up -d postgres redis

# 2. Instalar dependencias
pip install -e ".[dev]"

# 3. Migrar DB
PYTHONPATH=. alembic upgrade head

# 4. Seed portfolio + estrategias
PYTHONPATH=. python -m scripts.seed_paper_portfolio

# 5. Arrancar backend
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8001

# 6. Arrancar frontend
cd ../frontend
npm install
npx ng serve --port 4200
```

## Configuracion (.env)

```bash
# Basico
DEBUG=true
EXECUTION_MODE=PAPER
DATABASE_URL=postgresql+asyncpg://trading:trading_secret@localhost:5434/trading_db
REDIS_URL=redis://localhost:6381/0

# Binance (crypto)
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_TESTNET=true

# Alpaca (stocks USA)
ALPACA_ENABLED=true
ALPACA_API_KEY=PKxxxxxxxx
ALPACA_API_SECRET=xxxxxxxx
STOCK_SYMBOLS=AAPL,MSFT,GOOGL,AMZN,NVDA,TSLA,META,JPM,V,SPY
```

## Scripts

```bash
# Paper trading con background tasks
PYTHONPATH=. python -m scripts.start_paper_trading

# Simular trades (crypto + stocks)
PYTHONPATH=. python -m scripts.simulate_trades

# Descargar datos historicos
PYTHONPATH=. python -m scripts.download_historical           # crypto
PYTHONPATH=. python -m scripts.download_historical --stocks  # stocks

# Entrenar modelos ML
PYTHONPATH=. python -m scripts.train_model                   # crypto
PYTHONPATH=. python -m scripts.train_stock_model             # stocks

# Backtest
PYTHONPATH=. python -m scripts.run_backtest                  # crypto
PYTHONPATH=. python -m scripts.run_backtest --stocks         # stocks

# Tests
PYTHONPATH=. pytest tests/ -v
```

## Arquitectura

```
Frontend (Angular :4200)
    |
Backend (FastAPI :8001)
    |
    +-- Pipeline: Signal -> Risk -> Capital -> Guard -> Execute
    +-- Binance API (crypto 24/7)
    +-- Alpaca API (stocks 9:30-16:00 ET)
    +-- PostgreSQL :5434
    +-- Redis :6381
```

## Tests

323 tests unitarios cubriendo: orchestrator, risk manager, capital manager,
execution guard (crypto + stocks), market hours, AlpacaExecutor, routing
multi-exchange, stock momentum strategy, y flujo E2E de stocks.
