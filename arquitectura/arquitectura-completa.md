# Plataforma de Trading Algoritmico — Arquitectura Completa

> Documento de arquitectura consolidado.
> Fecha de creacion: 2026-03-19

---

## 1. Vision del Sistema

Plataforma de trading algoritmico modular, basada en senales probabilisticas y control estricto de riesgo para el mercado crypto spot.

### Decisiones Fundamentales

| Decision       | Eleccion                                  |
|----------------|-------------------------------------------|
| Exchange       | Binance (principal) + Bybit (futuro)      |
| Backend        | FastAPI (async nativo)                    |
| Frontend       | Angular (panel de control tactico)        |
| Mercado        | Crypto spot (no futures)                  |
| Ejecucion      | Paper trading obligatorio antes de real   |
| Base de datos  | PostgreSQL 16                             |
| Cache/Pub-Sub  | Redis 7                                   |
| Comunicacion   | REST (acciones) + WebSocket (tiempo real) |

---

## 2. Arquitectura General

```
                    +------------------------------+
                    |     Angular Frontend          |
                    |  (REST + WebSocket client)    |
                    +-------------+----------------+
                                  |
                    +-------------v----------------+
                    |     FastAPI Gateway           |
                    |  REST + WebSocket server      |
                    +-------------+----------------+
                                  |
                 +----------------v-----------------+
                 |      Trading Engine               |
                 |  (async event loop)               |
                 |                                   |
                 |  Market Feed --> Signal Engine     |
                 |       --> Strategy                 |
                 |       --> Risk Gate                |
                 |       --> Capital Allocator        |
                 |       --> Execution Guard          |
                 |       --> Order Executor           |
                 |       --> Position Manager         |
                 +---+---------------------+---------+
                     |                     |
              +------v----+  +-------------v---+
              | PostgreSQL |  |   Redis         |
              | (trades,   |  | (cache,         |
              |  events,   |  |  pub/sub,       |
              |  config)   |  |  rate limit,    |
              +------------+  |  system status) |
                              +-----------------+
```

---

## 3. Flujo del Pipeline

```
Market Data
   |
   v
Signal Engine (genera senales con confidence)
   |
   v
Strategy (combina senales, genera "edge")
   |
   v
Risk Manager --- puede BLOQUEAR o DETENER todo el sistema
   |
   v
Capital Manager (position sizing)
   |
   v
Execution Guard --- valida precio, spread, liquidez justo antes de ejecutar
   |
   v
Executor (paper o Binance real)
   |
   v
Position Manager (gestiona posiciones abiertas, SL, TP, trailing)
   |
   v
Trade Tracker (event sourcing, audit trail completo)
```

---

## 4. Estructura del Proyecto

```
Acciones/
|
+-- arquitectura/
|   +-- arquitectura-completa.md          # Este documento
|
+-- backend/
|   +-- alembic/                          # Migraciones DB
|   |   +-- versions/
|   |   +-- env.py
|   |   +-- alembic.ini
|   |
|   +-- app/
|   |   +-- __init__.py
|   |   +-- main.py                       # FastAPI app factory
|   |   +-- config.py                     # Settings via pydantic-settings
|   |   +-- dependencies.py              # DI: db session, redis, etc.
|   |   |
|   |   +-- core/                         # Concerns transversales
|   |   |   +-- __init__.py
|   |   |   +-- database.py              # Async engine, session factory
|   |   |   +-- redis.py                 # Redis connection pool
|   |   |   +-- security.py             # API key auth
|   |   |   +-- exceptions.py           # Excepciones de dominio
|   |   |   +-- logging.py              # Structured logging (structlog)
|   |   |   +-- events.py               # Event bus (in-process + Redis pub/sub)
|   |   |   +-- health.py               # Health monitor + kill switch global
|   |   |
|   |   +-- models/                       # SQLAlchemy ORM models
|   |   |   +-- __init__.py
|   |   |   +-- base.py                  # DeclarativeBase + mixins
|   |   |   +-- signal.py
|   |   |   +-- order.py
|   |   |   +-- position.py
|   |   |   +-- trade.py
|   |   |   +-- portfolio.py
|   |   |   +-- event_store.py           # Tabla event sourcing
|   |   |   +-- strategy_config.py
|   |   |   +-- risk_config.py
|   |   |
|   |   +-- schemas/                      # Pydantic v2 schemas
|   |   |   +-- __init__.py
|   |   |   +-- signal.py
|   |   |   +-- order.py
|   |   |   +-- position.py
|   |   |   +-- trade.py
|   |   |   +-- portfolio.py
|   |   |   +-- strategy.py
|   |   |   +-- risk.py
|   |   |   +-- websocket.py             # WS message envelopes
|   |   |
|   |   +-- domain/                       # Logica pura (sin I/O)
|   |   |   +-- __init__.py
|   |   |   +-- enums.py                 # SignalType, OrderStatus, etc.
|   |   |   +-- value_objects.py         # Money, Percentage, ConfidenceScore
|   |   |   +-- state_machine.py         # Transiciones Order/Position
|   |   |
|   |   +-- pipeline/                     # Core trading pipeline
|   |   |   +-- __init__.py
|   |   |   +-- orchestrator.py          # Conecta todo el pipeline
|   |   |   +-- signal_engine/
|   |   |   |   +-- __init__.py
|   |   |   |   +-- base.py             # Abstract signal generator
|   |   |   |   +-- rsi.py
|   |   |   |   +-- sma_crossover.py
|   |   |   |   +-- composite.py        # Combina multiples senales
|   |   |   +-- strategy/
|   |   |   |   +-- __init__.py
|   |   |   |   +-- base.py             # Abstract strategy
|   |   |   |   +-- momentum.py
|   |   |   +-- risk_manager/
|   |   |   |   +-- __init__.py
|   |   |   |   +-- risk_manager.py      # Core risk gate
|   |   |   |   +-- rules/
|   |   |   |   |   +-- daily_loss_limit.py
|   |   |   |   |   +-- max_drawdown.py
|   |   |   |   |   +-- min_confidence.py
|   |   |   |   |   +-- max_positions.py
|   |   |   |   |   +-- correlation.py
|   |   |   |   +-- circuit_breaker.py
|   |   |   +-- capital_manager/
|   |   |   |   +-- __init__.py
|   |   |   |   +-- capital_manager.py
|   |   |   +-- execution/
|   |   |   |   +-- __init__.py
|   |   |   |   +-- base.py             # Abstract executor
|   |   |   |   +-- guard.py            # Execution Guard (pre-ejecucion)
|   |   |   |   +-- paper_engine.py     # Paper trading simulator
|   |   |   |   +-- binance_executor.py # Binance real
|   |   |   +-- position_manager/
|   |   |   |   +-- __init__.py
|   |   |   |   +-- position_manager.py
|   |   |   +-- trade_tracker/
|   |   |       +-- __init__.py
|   |   |       +-- tracker.py
|   |   |
|   |   +-- services/                     # Servicios de aplicacion
|   |   |   +-- __init__.py
|   |   |   +-- market_data.py
|   |   |   +-- portfolio_service.py
|   |   |   +-- strategy_service.py
|   |   |   +-- analytics_service.py
|   |   |
|   |   +-- repositories/                # Data access layer
|   |   |   +-- __init__.py
|   |   |   +-- signal_repo.py
|   |   |   +-- order_repo.py
|   |   |   +-- position_repo.py
|   |   |   +-- trade_repo.py
|   |   |   +-- event_repo.py
|   |   |   +-- portfolio_repo.py
|   |   |
|   |   +-- exchange/                     # Exchange adapter layer
|   |   |   +-- __init__.py
|   |   |   +-- base.py                  # Abstract exchange interface
|   |   |   +-- binance_client.py        # Binance async REST
|   |   |   +-- binance_ws.py            # Binance WebSocket streams
|   |   |
|   |   +-- api/                          # FastAPI routers
|   |   |   +-- __init__.py
|   |   |   +-- v1/
|   |   |   |   +-- __init__.py
|   |   |   |   +-- router.py            # Agrega todas las rutas v1
|   |   |   |   +-- signals.py
|   |   |   |   +-- orders.py
|   |   |   |   +-- positions.py
|   |   |   |   +-- portfolio.py
|   |   |   |   +-- strategies.py
|   |   |   |   +-- risk.py
|   |   |   |   +-- analytics.py
|   |   |   |   +-- system.py            # Health, kill switch
|   |   |   +-- websocket/
|   |   |       +-- __init__.py
|   |   |       +-- ws_manager.py
|   |   |
|   |   +-- tasks/                        # Background tasks
|   |       +-- __init__.py
|   |       +-- market_data_collector.py
|   |       +-- signal_scanner.py
|   |
|   +-- tests/
|   |   +-- conftest.py
|   |   +-- unit/
|   |   |   +-- domain/
|   |   |   +-- pipeline/
|   |   |   +-- services/
|   |   +-- integration/
|   |   |   +-- test_pipeline_flow.py
|   |   |   +-- test_risk_rules.py
|   |   |   +-- test_paper_trading.py
|   |   +-- e2e/
|   |       +-- test_full_trade_cycle.py
|   |
|   +-- pyproject.toml
|   +-- Dockerfile
|   +-- docker-compose.yml
|
+-- frontend/                              # Angular
|   +-- src/app/
|       +-- core/
|       |   +-- services/
|       |   |   +-- websocket.service.ts
|       |   |   +-- api.service.ts
|       |   |   +-- auth.service.ts
|       |   +-- interceptors/
|       |   +-- guards/
|       +-- shared/
|       |   +-- components/
|       |   |   +-- price-ticker/
|       |   |   +-- status-badge/
|       |   +-- models/
|       |       +-- signal.model.ts
|       |       +-- order.model.ts
|       |       +-- position.model.ts
|       |       +-- trade.model.ts
|       +-- features/
|       |   +-- dashboard/
|       |   |   +-- dashboard.component.ts
|       |   |   +-- widgets/
|       |   |   |   +-- balance-card/
|       |   |   |   +-- pnl-chart/
|       |   |   |   +-- win-rate/
|       |   |   |   +-- drawdown-chart/
|       |   |   +-- dashboard.routes.ts
|       |   +-- trades/
|       |   |   +-- trade-list/
|       |   |   +-- trade-detail/
|       |   |   +-- live-trades/
|       |   |   +-- trades.routes.ts
|       |   +-- strategies/
|       |   |   +-- strategy-list/
|       |   |   +-- strategy-config/
|       |   |   +-- strategies.routes.ts
|       |   +-- risk-panel/
|       |       +-- risk-overview/
|       |       +-- circuit-breaker/
|       |       +-- alerts/
|       |       +-- risk.routes.ts
|       +-- store/                         # NgRx
|       |   +-- portfolio/
|       |   +-- signals/
|       |   +-- positions/
|       |   +-- risk/
|       +-- app.routes.ts
|
+-- scripts/
|   +-- seed_paper_portfolio.py
|   +-- backtest_runner.py
|
+-- .env.example
+-- .gitignore
```

---

## 5. Modelos de Dominio

### 5.1 Enumeraciones

```python
class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    SIZED = "SIZED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

class PositionStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"
    STOPPED_OUT = "STOPPED_OUT"

class ExecutionMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"

class RiskAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REDUCE_SIZE = "REDUCE_SIZE"
    HALT_SYSTEM = "HALT_SYSTEM"
```

### 5.2 Signal (modelo enriquecido)

```python
class Signal:
    symbol: str
    signal_type: SignalType       # BUY / SELL / HOLD
    confidence: float             # 0.0 - 1.0
    timeframe: str                # "1m", "5m", "1h"
    indicators: dict              # {"rsi": 28, "sma_cross": True}
    entry_price: Decimal          # precio objetivo de entrada
    stop_loss: Decimal            # OBLIGATORIO
    take_profit: Decimal          # OBLIGATORIO
    strategy_id: UUID
    expires_at: datetime          # senal con vida util
```

---

## 6. Esquema de Base de Datos

### Tabla: events (event sourcing)

| Columna         | Tipo          | Notas                                      |
|-----------------|---------------|---------------------------------------------|
| id              | UUID (PK)     |                                             |
| aggregate_type  | VARCHAR(50)   | "Order", "Position", "Signal"               |
| aggregate_id    | UUID          | ID logico de la entidad                     |
| event_type      | VARCHAR(100)  | "OrderCreated", "RiskApproved", etc.        |
| event_data      | JSONB         | Payload completo                            |
| metadata        | JSONB         | correlation_id, causation_id                |
| sequence_number | BIGINT        | Contador monotonico por agregado            |
| created_at      | TIMESTAMPTZ   | Inmutable                                   |

Particionada por mes (PARTITION BY RANGE created_at).
Unique constraint: (aggregate_id, sequence_number).

### Tabla: signals

| Columna      | Tipo            |
|--------------|-----------------|
| id           | UUID (PK)       |
| symbol       | VARCHAR(20)     |
| signal_type  | ENUM            |
| confidence   | DECIMAL(5,4)    |
| timeframe    | VARCHAR(10)     |
| indicators   | JSONB           |
| entry_price  | DECIMAL(20,8)   |
| stop_loss    | DECIMAL(20,8)   |
| take_profit  | DECIMAL(20,8)   |
| strategy_id  | UUID (FK)       |
| expires_at   | TIMESTAMPTZ     |
| created_at   | TIMESTAMPTZ     |

### Tabla: orders

| Columna            | Tipo            |
|--------------------|-----------------|
| id                 | UUID (PK)       |
| signal_id          | UUID (FK)       |
| symbol             | VARCHAR(20)     |
| side               | ENUM(BUY/SELL)  |
| order_type         | ENUM(MARKET/LIMIT) |
| status             | ENUM(OrderStatus) |
| requested_qty      | DECIMAL(20,8)   |
| filled_qty         | DECIMAL(20,8)   |
| requested_price    | DECIMAL(20,8)   |
| avg_fill_price     | DECIMAL(20,8)   |
| stop_loss          | DECIMAL(20,8)   |
| take_profit        | DECIMAL(20,8)   |
| execution_mode     | ENUM(PAPER/LIVE)|
| exchange_order_id  | VARCHAR(100)    |
| risk_decision      | JSONB           |
| capital_decision   | JSONB           |
| created_at         | TIMESTAMPTZ     |
| updated_at         | TIMESTAMPTZ     |

### Tabla: positions

| Columna         | Tipo            |
|-----------------|-----------------|
| id              | UUID (PK)       |
| symbol          | VARCHAR(20)     |
| side            | ENUM(LONG)      |
| status          | ENUM(PositionStatus) |
| entry_order_id  | UUID (FK)       |
| entry_price     | DECIMAL(20,8)   |
| current_price   | DECIMAL(20,8)   |
| quantity        | DECIMAL(20,8)   |
| stop_loss       | DECIMAL(20,8)   |
| take_profit     | DECIMAL(20,8)   |
| unrealized_pnl  | DECIMAL(20,8)   |
| realized_pnl    | DECIMAL(20,8)   |
| opened_at       | TIMESTAMPTZ     |
| closed_at       | TIMESTAMPTZ     |

### Tabla: trades (posicion cerrada)

| Columna            | Tipo            |
|--------------------|-----------------|
| id                 | UUID (PK)       |
| position_id        | UUID (FK)       |
| symbol             | VARCHAR(20)     |
| entry_price        | DECIMAL(20,8)   |
| exit_price         | DECIMAL(20,8)   |
| quantity           | DECIMAL(20,8)   |
| pnl                | DECIMAL(20,8)   |
| pnl_percent        | DECIMAL(8,4)    |
| signal_confidence  | DECIMAL(5,4)    |
| strategy_id        | UUID (FK)       |
| execution_mode     | ENUM            |
| duration_seconds   | INTEGER         |
| opened_at          | TIMESTAMPTZ     |
| closed_at          | TIMESTAMPTZ     |

### Tabla: portfolio

| Columna            | Tipo            |
|--------------------|-----------------|
| id                 | UUID (PK)       |
| execution_mode     | ENUM            |
| total_balance      | DECIMAL(20,8)   |
| available_balance  | DECIMAL(20,8)   |
| allocated_balance  | DECIMAL(20,8)   |
| total_pnl          | DECIMAL(20,8)   |
| daily_pnl          | DECIMAL(20,8)   |
| max_drawdown       | DECIMAL(8,4)    |
| updated_at         | TIMESTAMPTZ     |

---

## 7. State Machine — Ciclo de Vida

### Order Lifecycle

```
PENDING --[risk_validate]--> VALIDATED --[capital_size]--> SIZED --[submit]--> SUBMITTED
   |                            |                                       |
   |                            |                                       +-> PARTIALLY_FILLED --> FILLED
   |                            |                                       |
   +-> REJECTED                 +-> REJECTED                           +-> CANCELLED / EXPIRED
                                     (risk blocked)
                                                                    FILLED --> [crea Position OPEN]
```

### Position Lifecycle

```
OPEN --[partial_close]--> PARTIALLY_CLOSED --[full_close]--> CLOSED
  |                                                             |
  +--[stop_loss_hit]--> STOPPED_OUT                            +--> [crea Trade record]
```

Cada transicion es atomica: una transaccion DB que actualiza el estado Y escribe el evento correspondiente al event store.

---

## 8. Componentes Criticos Detallados

### 8.1 Orchestrator (Pipeline)

```python
async def execute_pipeline(signal: Signal) -> PipelineResult:
    # 0. Check sistema activo
    if await redis.get("system:status") == "HALTED":
        return PipelineResult(action="SYSTEM_HALTED")

    # 1. Strategy evalua senal
    intent = await strategy.evaluate(signal)
    if intent.action == HOLD:
        return PipelineResult(action="HOLD", reason="No edge")

    # 2. Risk Manager — PUEDE BLOQUEAR TODO
    risk_decision = await risk_manager.validate(intent, portfolio)
    if risk_decision.action == REJECT:
        await event_store.append(RiskRejectedEvent(...))
        return PipelineResult(action="REJECTED", reason=risk_decision.reason)
    if risk_decision.action == HALT_SYSTEM:
        await circuit_breaker.activate(reason=risk_decision.reason)
        return PipelineResult(action="HALTED")

    # 3. Capital Manager calcula tamano
    sizing = await capital_manager.calculate_size(intent, risk_decision, portfolio)

    # 4. Crear orden
    order = await order_service.create(intent, sizing, risk_decision)

    # 5. Execution Guard — validacion pre-ejecucion
    guard_result = await execution_guard.validate(order, market_snapshot)
    if guard_result.action == REJECT:
        await event_store.append(GuardRejectedEvent(...))
        return PipelineResult(action="GUARD_REJECTED", reason=guard_result.reason)

    # 6. Ejecutar (paper o real)
    fill = await executor.submit(order)

    # 7. Position Manager
    position = await position_manager.handle_fill(fill, order)

    # 8. Trade Tracker
    await trade_tracker.record(signal, order, fill, position)

    return PipelineResult(action="EXECUTED", order=order, position=position)
```

### 8.2 Execution Guard (validacion pre-ejecucion)

```python
class ExecutionGuard:
    async def validate(self, order: Order, market: MarketSnapshot) -> GuardResult:
        # 1. Precio sigue valido (no se movio mas de X%)
        price_drift = abs(market.price - order.entry_price) / order.entry_price
        if price_drift > self.max_price_drift:  # ej: 0.5%
            return GuardResult.REJECT("price_drift", f"{price_drift:.2%}")

        # 2. Spread aceptable
        spread = (market.ask - market.bid) / market.bid
        if spread > self.max_spread:  # ej: 0.3%
            return GuardResult.REJECT("spread_too_wide", f"{spread:.2%}")

        # 3. Volumen/liquidez minima
        if market.volume_24h < self.min_volume:
            return GuardResult.REJECT("low_liquidity")

        # 4. Profundidad del order book
        if order.quantity > market.best_ask_qty * self.max_book_ratio:
            return GuardResult.REDUCE_SIZE(market.best_ask_qty * self.max_book_ratio)

        return GuardResult.APPROVE()
```

### 8.3 Risk Manager

```python
class RiskManager:
    def __init__(self, rules: list[RiskRule]):
        self.rules = rules  # daily_loss, max_drawdown, min_confidence, max_positions, correlation

    async def validate(self, intent, portfolio) -> RiskDecision:
        for rule in self.rules:
            result = await rule.evaluate(intent, portfolio)
            if result.action != APPROVE:
                return result  # Primera regla que falla, bloquea
        return RiskDecision(action=APPROVE)
```

### 8.4 Capital Manager

```python
class CapitalManager:
    async def calculate_size(self, intent, risk_decision, portfolio) -> Sizing:
        risk_per_trade = Decimal("0.01")  # 1% del portfolio

        # Distancia al stop loss
        distance = abs(intent.entry_price - intent.stop_loss) / intent.entry_price

        # Tamano basado en riesgo
        risk_amount = portfolio.available_balance * risk_per_trade * intent.confidence
        quantity = risk_amount / (intent.entry_price * distance)

        # Ajustar por exposicion existente
        existing_exposure = await self._get_symbol_exposure(intent.symbol, portfolio)
        max_per_symbol = portfolio.total_balance * Decimal("0.1")  # max 10% por simbolo
        if existing_exposure + (quantity * intent.entry_price) > max_per_symbol:
            quantity = (max_per_symbol - existing_exposure) / intent.entry_price

        return Sizing(quantity=quantity, risk_amount=risk_amount)
```

### 8.5 System Health Monitor + Kill Switch

```python
class SystemHealthMonitor:
    """Background task que corre cada 5 segundos"""

    async def check(self) -> HealthStatus:
        checks = {
            "binance_api": await self._check_binance_latency(),
            "binance_ws": self._check_ws_alive(),
            "database": await self._check_db(),
            "redis": await self._check_redis(),
            "circuit_breaker": self._check_circuit_breaker(),
            "daily_drawdown": await self._check_drawdown(),
        }

        if any(c.status == CRITICAL for c in checks.values()):
            await self.global_halt(reason=checks)

        return HealthStatus(checks)

    async def global_halt(self, reason: dict):
        """DETIENE TODO"""
        # 1. Cancela senales pendientes
        # 2. NO cierra posiciones abiertas (podria ser peor)
        # 3. Marca sistema como HALTED en Redis
        # 4. Notifica via WebSocket al frontend
        # 5. Log evento SYSTEM_HALTED
        await redis.set("system:status", "HALTED")
        await event_store.append(SystemHaltedEvent(reason=reason))
        await ws_manager.broadcast("system", {"status": "HALTED", "reason": reason})
```

Endpoints:

```
POST /api/v1/system/halt     # Kill switch manual desde frontend
POST /api/v1/system/resume   # Reanudar (requiere confirmacion)
GET  /api/v1/system/health   # Estado actual de todos los checks
```

### 8.6 Strategy Isolation

```python
class StrategyRunner:
    async def run_strategy(self, strategy: Strategy, market_data: MarketData):
        try:
            async with asyncio.timeout(5):  # timeout por estrategia
                signal = await strategy.evaluate(market_data)
                return signal
        except Exception as e:
            logger.error("strategy_failed", strategy=strategy.id, error=str(e))
            await self._record_failure(strategy.id)
            if await self._consecutive_failures(strategy.id) >= 3:
                await self._deactivate(strategy.id)
                await event_store.append(StrategyDeactivatedEvent(...))
            return None  # NO propaga, otras estrategias siguen

async def run_all_strategies(strategies, market_data):
    tasks = [runner.run_strategy(s, market_data) for s in strategies if s.is_active]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    signals = [r for r in results if isinstance(r, Signal)]
    return signals
```

### 8.7 Position Manager (faseado)

```python
class PositionManager:
    # Fase 4: Core
    async def open_position(self, fill, order) -> Position
    async def close_position(self, position_id, reason) -> Trade
    async def check_stop_loss(self, position, price) -> bool
    async def check_take_profit(self, position, price) -> bool

    # Fase 5: Partial closes
    async def partial_close(self, position_id, percentage) -> Trade

    # Fase 6: Trailing stop
    async def update_trailing_stop(self, position, price)

    # Fase 7: Break-even automatico
    async def check_breakeven_trigger(self, position, price)
```

Monitor de precios (background task):

```python
async def position_monitor(position_manager, price_stream):
    async for tick in price_stream:
        open_positions = await position_manager.get_open_by_symbol(tick.symbol)
        for pos in open_positions:
            if await position_manager.check_stop_loss(pos, tick.price):
                await pipeline.close_position(pos, reason="STOP_LOSS")
            elif await position_manager.check_take_profit(pos, tick.price):
                await pipeline.close_position(pos, reason="TAKE_PROFIT")
```

### 8.8 Paper Trading Engine

```python
class PaperEngine(BaseExecutor):
    """Mismo interface que BinanceExecutor"""

    async def submit(self, order: Order) -> Fill:
        # Market orders: fill al precio actual + slippage simulado (0.05%)
        current_price = await self.price_feed.get_price(order.symbol)
        slippage = current_price * Decimal("0.0005")
        fill_price = current_price + slippage if order.side == BUY else current_price - slippage

        # Latencia simulada (100-500ms)
        await asyncio.sleep(random.uniform(0.1, 0.5))

        # Actualizar balance virtual
        await self.portfolio_service.deduct(order.symbol, fill_price * order.quantity)

        return Fill(
            order_id=order.id,
            price=fill_price,
            quantity=order.quantity,
            timestamp=datetime.utcnow(),
            execution_mode=ExecutionMode.PAPER,
        )
```

---

## 9. Event Sourcing — Eventos del Sistema

Todos los eventos registrados en la tabla `events`:

| Evento                        | Cuando                                     |
|-------------------------------|---------------------------------------------|
| SignalGenerated               | Signal engine produce una senal             |
| SignalExpired                 | Senal supera su expires_at                  |
| RiskApproved                  | Risk manager aprueba                        |
| RiskRejected                  | Risk manager bloquea (incluye razon)        |
| GuardApproved                 | Execution guard aprueba                     |
| GuardRejected                 | Execution guard bloquea (precio, spread)    |
| OrderCreated                  | Orden creada en el sistema                  |
| OrderSized                    | Capital manager asigna tamano               |
| OrderSubmitted                | Orden enviada al executor                   |
| OrderFilled                   | Orden ejecutada completamente               |
| OrderCancelled                | Orden cancelada                             |
| PositionOpened                | Posicion abierta tras fill                  |
| StopLossUpdated               | SL modificado (trailing, break-even)        |
| PositionPartiallyClosed       | Cierre parcial ejecutado                    |
| PositionClosed                | Posicion cerrada completamente              |
| StopLossTriggered             | SL alcanzado                                |
| TakeProfitTriggered           | TP alcanzado                                |
| CircuitBreakerActivated       | Sistema detenido por regla de riesgo        |
| CircuitBreakerReset           | Sistema reactivado                          |
| SystemHalted                  | Kill switch global activado                 |
| SystemResumed                 | Sistema reanudado                           |
| StrategyDeactivated           | Estrategia desactivada por fallos           |
| DailyLossLimitReached         | Limite diario de perdida alcanzado          |

Cada evento lleva:
- `correlation_id`: liga a la senal original
- `causation_id`: evento que lo causo directamente

---

## 10. API Endpoints

### REST (acciones y consultas)

```
# Sistema
GET  /api/v1/system/health
POST /api/v1/system/halt
POST /api/v1/system/resume

# Market Data
GET  /api/v1/market/ticker/{symbol}
GET  /api/v1/market/klines/{symbol}

# Signals
GET  /api/v1/signals
GET  /api/v1/signals/{id}

# Orders
GET  /api/v1/orders
GET  /api/v1/orders/{id}

# Positions
GET  /api/v1/positions
GET  /api/v1/positions/open
GET  /api/v1/positions/{id}
POST /api/v1/positions/{id}/close

# Trades
GET  /api/v1/trades
GET  /api/v1/trades/{id}

# Portfolio
GET  /api/v1/portfolio
GET  /api/v1/portfolio/metrics

# Strategies
GET  /api/v1/strategies
POST /api/v1/strategies
PUT  /api/v1/strategies/{id}
POST /api/v1/strategies/{id}/activate
POST /api/v1/strategies/{id}/deactivate

# Risk
GET  /api/v1/risk/config
PUT  /api/v1/risk/config
GET  /api/v1/risk/status

# Analytics
GET  /api/v1/analytics/pnl
GET  /api/v1/analytics/drawdown
GET  /api/v1/analytics/win-rate
GET  /api/v1/analytics/per-strategy
```

### WebSocket (tiempo real)

```
WS /ws

Canales:
- prices:{symbol}    -> actualizaciones de precio en tiempo real
- signals            -> nuevas senales generadas
- orders             -> cambios de estado de ordenes
- positions          -> updates de posiciones (unrealized PnL)
- risk               -> alertas de riesgo, circuit breaker
- portfolio          -> balance y PnL updates
- system             -> estado del sistema, health
```

---

## 11. Decisiones Arquitectonicas Clave

| # | Decision | Razon |
|---|----------|-------|
| 1 | FastAPI sobre Flask | Async nativo, WebSocket nativo, Pydantic integrado. Evita parchar Flask con Celery + SocketIO |
| 2 | Event sourcing ligero, no full CQRS | Eventos + projections en misma transaccion. Evita consistencia eventual innecesaria para single-user |
| 3 | Executor abstracto | Paper y Binance comparten interface. Garantiza que paper testing ejercita el mismo codigo que produccion |
| 4 | Risk Manager como gate binario | No ajusta senales, las aprueba o rechaza. Simplicidad = seguridad |
| 5 | Redis pub/sub, no Kafka | Suficiente para single-user. PostgreSQL es el registro durable |
| 6 | Decimal everywhere | Nunca float para dinero. DECIMAL(20,8) en PostgreSQL, Decimal en Python |
| 7 | Pipeline lineal async (no colas) | Para Fase 1-4. Migrar a colas asyncio.Queue solo si se mide bottleneck real |
| 8 | Execution Guard antes del executor | Valida precio, spread, liquidez justo antes de ejecutar. Protege contra slippage y ejecuciones malas |
| 9 | Particion de events por mes | Desde la primera migracion. Previene degradacion a largo plazo sin sobre-ingenieria |
| 10 | Strategy isolation con asyncio.gather | Timeout individual, auto-desactivacion tras 3 fallos consecutivos. Una estrategia no tumba a otra |

---

## 12. Stack Tecnologico

### Backend

| Componente       | Tecnologia                    |
|------------------|-------------------------------|
| Framework        | FastAPI                       |
| Server           | Uvicorn                       |
| ORM              | SQLAlchemy 2.0 (async)        |
| DB Driver        | asyncpg                       |
| Migraciones      | Alembic                       |
| Validacion       | Pydantic v2                   |
| Config           | pydantic-settings             |
| Cache/Pub-Sub    | Redis (redis-py async + hiredis) |
| Exchange         | python-binance                |
| Indicadores      | pandas-ta                     |
| Logging          | structlog                     |
| Testing          | pytest + pytest-asyncio + httpx |

### Frontend

| Componente       | Tecnologia                    |
|------------------|-------------------------------|
| Framework        | Angular                       |
| State            | NgRx                          |
| WebSocket        | RxJS webSocket                |
| Charts           | lightweight-charts             |
| UI               | Angular Material (o similar)  |

### Infraestructura

| Componente       | Tecnologia                    |
|------------------|-------------------------------|
| Base de datos    | PostgreSQL 16                 |
| Cache            | Redis 7                       |
| Contenedores     | Docker + Docker Compose       |
| App Server       | Uvicorn (multi-worker)        |

---

## 13. Plan de Fases

### Fase 0 — Foundation (Semana 1)

- Estructura del proyecto (backend + frontend scaffolding)
- pyproject.toml con dependencias
- docker-compose.yml (PostgreSQL + Redis + app)
- SQLAlchemy async setup, Base model con mixins
- Alembic configuracion async
- FastAPI app factory con health endpoint
- config.py con pydantic-settings
- Structured logging con structlog
- Angular project init, routing basico

**Entregable**: `docker compose up` levanta FastAPI con health check, conectado a PostgreSQL y Redis.

### Fase 1 — Domain + Data Layer (Semana 2)

- Todos los enums en domain/enums.py
- Todos los modelos SQLAlchemy
- Migracion inicial Alembic (incluyendo particion de events)
- Todos los schemas Pydantic
- Repository layer (CRUD async)
- Event store: append, query por aggregate, query por correlation_id
- State machine: transiciones definidas, funcion transition() atomica
- Tests unitarios para state machine y value objects

**Entregable**: Data layer completo con migraciones, logica de dominio testeable.

### Fase 2 — Market Data + Signal Engine (Semana 3)

- exchange/binance_client.py: wrapper async REST (klines, ticker, exchange info)
- exchange/binance_ws.py: WebSocket streams con reconexion
- Cache Redis para exchange info y precios recientes
- Signal engine: base abstracta, RSI, SMA crossover
- Composite signal combiner
- Strategy isolation (asyncio.gather + timeout + auto-deactivate)
- Background task: signal_scanner.py
- api/v1/signals.py
- Tests con mock Binance

**Entregable**: Sistema conecta a Binance, ingesta precios, genera senales.

### Fase 3 — Risk + Capital Management (Semana 4)

- Reglas de riesgo: daily loss, max drawdown, min confidence, max positions, max exposure
- risk_manager.py: evalua todas las reglas
- Circuit breaker: activar/desactivar con evento
- capital_manager.py: sizing por riesgo/distancia-SL
- Sizing ajustado por correlacion y exposicion existente
- api/v1/risk.py
- Tests extensivos para cada regla

**Entregable**: Risk manager aprueba/rechaza/detiene, capital manager calcula tamanos correctos.

### Fase 4 — Paper Trading + Pipeline Completo (Semana 5-6)

- execution/base.py: interface abstracta
- execution/guard.py: Execution Guard
- execution/paper_engine.py: simulador completo
- pipeline/orchestrator.py: conecta todo el pipeline
- position_manager.py: open, close, SL, TP
- trade_tracker.py: escribe eventos por cada paso
- core/health.py: SystemHealthMonitor + kill switch
- api/v1/system.py: halt, resume, health
- Portfolio service: actualiza balances tras fills
- Background task: position_monitor (SL/TP triggers)
- scripts/seed_paper_portfolio.py (10,000 USDT)
- Tests de integracion: pipeline completo

**Entregable**: Paper trading funcional end-to-end con audit trail.

### Fase 5 — WebSocket + Frontend Core (Semana 7-8)

- ws_manager.py: connection manager + Redis pub/sub
- Pipeline publica eventos a Redis en cada cambio de estado
- Angular websocket.service.ts con RxJS
- NgRx store para portfolio, positions, signals, risk
- Dashboard: balance, PnL chart, win rate, drawdown
- Trades: lista en vivo, historial con filtros
- Price ticker en tiempo real

**Entregable**: Dashboard Angular mostrando paper trading en vivo.

### Fase 6 — Strategy Management + Risk Panel UI (Semana 9)

- api/v1/strategies.py: CRUD, activar/desactivar
- Angular strategies: lista, configuracion, toggle
- Angular risk panel: limites, circuit breaker, alertas
- Trades detail: esperado vs real
- Analytics service: drawdown chart, PnL acumulado, performance por estrategia
- Position Manager: partial closes, trailing stop

**Entregable**: Panel de control completo.

### Fase 7 — Hardening + Live Preparation (Semana 10-11)

- API key authentication
- Rate limiting (Redis)
- execution/binance_executor.py: Binance Spot Testnet
- Parallel run: paper + testnet simultaneo, comparar resultados
- Error handling: exchange errors, network failures, partial fills
- Idempotencia en order submission
- Graceful shutdown
- Position Manager: break-even automatico

**Entregable**: Sistema listo para testnet.

### Fase 8 — Go Live (Semana 12)

- Switch a Binance production API
- Capital minimo, estrategia unica
- Modo aprobacion manual opcional (senal generada, humano aprueba via UI)
- Notificaciones: Telegram/Discord para fills, SL, circuit breaker
- Comparacion paper vs live

**Entregable**: Sistema en produccion con dinero real.

---

## 14. Reglas de Oro

1. **Decimal, nunca float** para cualquier valor monetario
2. **Todo pasa por el Risk Manager** — sin excepciones
3. **Event sourcing para cada decision** — si no quedo registrado, no paso
4. **Paper primero, real despues** — siempre
5. **El sistema puede detenerse solo** — kill switch automatico y manual
6. **Una estrategia no tumba a otra** — aislamiento obligatorio
7. **Medir antes de optimizar** — pipeline lineal hasta que se demuestre insuficiente
