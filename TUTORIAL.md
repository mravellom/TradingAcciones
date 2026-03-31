# Tutorial Exhaustivo: Sistema de Trading Automatizado

## Tabla de Contenidos

1. [Vista General](#1-vista-general)
2. [Arquitectura](#2-arquitectura)
3. [Flujo de Datos Completo](#3-flujo-de-datos-completo)
4. [Backend: Módulo por Módulo](#4-backend-módulo-por-módulo)
5. [Pipeline de Trading (el corazón)](#5-pipeline-de-trading)
6. [Machine Learning](#6-machine-learning)
7. [Sistema de Riesgo](#7-sistema-de-riesgo)
8. [Reconciliación y Seguridad](#8-reconciliación-y-seguridad)
9. [Frontend Angular](#9-frontend-angular)
10. [Base de Datos](#10-base-de-datos)
11. [Configuración y Deployment](#11-configuración-y-deployment)
12. [Glosario](#12-glosario)

---

## 1. Vista General

### Qué es este sistema

Un bot de trading automatizado para criptomonedas en Binance. Analiza el mercado con indicadores técnicos (RSI, SMA) y Machine Learning (XGBoost), toma decisiones de compra/venta, gestiona riesgo, y ejecuta operaciones — todo de forma autónoma.

### Stack tecnológico

```
Backend:   Python 3.11 + FastAPI (async)
Frontend:  Angular 18 + TypeScript
DB:        PostgreSQL 16
Cache:     Redis 7
Exchange:  Binance API (REST + WebSocket)
ML:        XGBoost + pandas + pandas-ta
Container: Docker + Docker Compose
```

### Estructura de carpetas

```
Acciones/
├── backend/
│   ├── app/                    # Código principal
│   │   ├── api/                # Endpoints REST + WebSocket
│   │   ├── core/               # Infraestructura (DB, Redis, auth, logging)
│   │   ├── domain/             # Reglas de negocio (enums, state machine)
│   │   ├── exchange/           # Conexión con Binance
│   │   ├── ml/                 # Machine Learning completo
│   │   ├── models/             # Modelos de base de datos (SQLAlchemy)
│   │   ├── pipeline/           # Motor de trading (orchestrator, risk, execution)
│   │   ├── repositories/       # Acceso a datos (queries)
│   │   ├── schemas/            # Validación de request/response
│   │   ├── services/           # Lógica de negocio
│   │   └── tasks/              # Background tasks (scanner, monitor, reconciler)
│   ├── alembic/                # Migraciones de DB
│   ├── ml_data/                # Modelos ML entrenados + datos
│   ├── scripts/                # Scripts de utilidad
│   └── tests/                  # Tests unitarios e integración
├── frontend/                   # Dashboard Angular
└── arquitectura/               # Documentación de arquitectura
```

---

## 2. Arquitectura

### Diagrama de componentes

```
┌──────────────────────────────────────────────────────┐
│                    FRONTEND (Angular)                  │
│                   localhost:4200                       │
│  Dashboard │ Strategies │ Trades │ Risk Panel          │
└──────────────────────┬───────────────────────────────┘
                       │ HTTP + WebSocket
┌──────────────────────┴───────────────────────────────┐
│                  BACKEND (FastAPI)                     │
│                  localhost:8000                        │
│                                                       │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │  REST API   │  │  WebSocket   │  │ Background  │ │
│  │  /api/v1/*  │  │  /ws         │  │   Tasks     │ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘ │
│         │                │                  │        │
│  ┌──────┴────────────────┴──────────────────┴─────┐  │
│  │              PIPELINE DE TRADING               │  │
│  │  Signal → Risk → Capital → Guard → Execute     │  │
│  └──────────────────────┬─────────────────────────┘  │
│                         │                            │
│  ┌──────────┐  ┌───────┴──────┐  ┌───────────────┐  │
│  │   ML     │  │  Position    │  │  Reconciler   │  │
│  │ XGBoost  │  │  Manager     │  │  (runtime)    │  │
│  └──────────┘  └──────────────┘  └───────────────┘  │
└────────┬──────────────┬──────────────────┬───────────┘
         │              │                  │
    ┌────┴────┐   ┌─────┴─────┐    ┌──────┴──────┐
    │ Binance │   │PostgreSQL │    │    Redis    │
    │  API    │   │   :5434   │    │    :6381    │
    └─────────┘   └───────────┘    └─────────────┘
```

### Patrón de comunicación

- **Frontend → Backend**: HTTP REST para acciones, WebSocket para datos en tiempo real
- **Backend → Binance**: REST API para órdenes y datos, WebSocket para precios en vivo
- **Backend → PostgreSQL**: SQLAlchemy async para persistencia
- **Backend → Redis**: Cache de precios, estado del sistema, circuit breaker, pub/sub

---

## 3. Flujo de Datos Completo

### Desde señal hasta trade cerrado (el ciclo completo)

```
PASO 1: OBTENER DATOS
─────────────────────
Binance API → get_klines("BTCUSDT", "1h", 100)
           → Retorna 100 velas de 1 hora
           → Cada vela: open, high, low, close, volume

PASO 2: GENERAR SEÑAL
─────────────────────
Signal Scanner (cada 60 segundos):
  │
  ├→ RSI Generator:
  │   RSI = 28.5 (< 30 = sobreventa) → BUY, confidence=0.72
  │
  ├→ SMA Crossover:
  │   SMA(9) > SMA(21) → Golden Cross → BUY, confidence=0.65
  │
  └→ ML XGBoost:
      Features: RSI, SMA, ATR, MACD, volume... (40+ features)
      Probability: 0.74 (> threshold 0.69) → BUY, confidence=0.78

  Composite (ponderado):
    ML: 60% × 0.78 = 0.468
    RSI: 20% × 0.72 = 0.144
    SMA: 20% × 0.65 = 0.130
    Total: 0.742 → TradeIntent(BUY, confidence=0.742)

PASO 3: EVALUAR RIESGO
──────────────────────
Risk Manager evalúa 5 reglas en orden:
  ✅ MinConfidence: 0.742 > 0.60 → PASS
  ✅ DailyLossLimit: PnL diario -1.2% < -3% límite → PASS
  ✅ MaxDrawdown: drawdown 4% < 10% límite → PASS
  ✅ MaxPositions: 2 abiertas < 5 máximo → PASS
  ✅ MaxExposure: BTCUSDT 5% < 10% límite → PASS
  → APPROVED

PASO 4: CALCULAR TAMAÑO
────────────────────────
Capital Manager:
  Balance disponible: $8,000
  Risk per trade: 1% = $80
  Stop loss distance: 2% ($1,000)
  Position size: $80 / 2% = $4,000
  Quantity: $4,000 / $50,000 = 0.08 BTC

PASO 5: VALIDAR MERCADO
────────────────────────
Execution Guard:
  ✅ Price drift: 0.1% < 0.5% → OK
  ✅ Spread: 0.02% < 0.3% → OK
  ✅ Volume 24h: $75M > $100K → OK
  → APPROVED

PASO 6: EJECUTAR
─────────────────
Paper Engine (modo PAPER):
  Simula compra 0.08 BTC @ $50,025 (con 0.05% slippage)
  Fill: price=$50,025, qty=0.08, slippage=$25

Binance Executor (modo LIVE):
  POST /api/v3/order {symbol: BTCUSDT, side: BUY, type: MARKET, qty: 0.08}
  Binance responde: orderId=12345, fills=[{price: 50025, qty: 0.08}]

PASO 7: CREAR POSICIÓN
───────────────────────
Position Manager:
  Position(
    symbol=BTCUSDT, side=LONG,
    entry_price=50025, quantity=0.08,
    stop_loss=49025, take_profit=52025,
    status=OPEN
  )

PASO 8: ACTUALIZAR PORTFOLIO
────────────────────────────
Portfolio:
  available_balance: $8,000 → $3,998 (se resta $4,002)
  allocated_balance: $2,000 → $6,002 (se suma $4,002)
  total_balance: $10,000 (no cambia)

PASO 9: MONITOREAR (continuo)
─────────────────────────────
Position Monitor (cada 2-5 segundos):
  Lee precio actual de Redis cache
  Precio actual: $50,500
  ¿$50,500 <= $49,025 (SL)? → NO
  ¿$50,500 >= $52,025 (TP)? → NO
  → Actualiza unrealized_pnl = ($50,500 - $50,025) × 0.08 = $38

  ... 3 horas después ...

  Precio actual: $52,100
  ¿$52,100 >= $52,025 (TP)? → SÍ → TAKE PROFIT!

PASO 10: CERRAR POSICIÓN
─────────────────────────
Position Manager:
  Exit price: $52,100
  PnL: ($52,100 - $50,025) × 0.08 = $166
  PnL%: +4.15%
  Position status: CLOSED → Trade record creado

PASO 11: ACTUALIZAR PORTFOLIO
─────────────────────────────
Portfolio:
  allocated_balance: $6,002 → $2,000
  available_balance: $3,998 → $8,168 (+$166 profit)
  total_balance: $10,000 → $10,168
  total_pnl: +$168
```

---

## 4. Backend: Módulo por Módulo

### 4.1 Core (`app/core/`)

La infraestructura base que todo el sistema usa.

#### `database.py` — Conexión a PostgreSQL
```python
# Motor async de SQLAlchemy
engine = create_async_engine(settings.database_url)

# Fábrica de sesiones — cada request HTTP obtiene su propia sesión
async_session_factory = async_sessionmaker(engine)

# Patrón: session → yield → commit/rollback automático
async def get_db():
    async with async_session_factory() as session:
        yield session
        await session.commit()
```

**Por qué importa:** Cada operación de trading corre dentro de una transacción de base de datos. Si algo falla, todo se revierte (atomicidad). No se puede crear una posición sin actualizar el balance.

#### `redis.py` — Cache y estado
Redis se usa para:
- **Cache de precios**: `price:BTCUSDT` → último precio de Binance (TTL 30s)
- **Estado del sistema**: `system:status` → RUNNING/HALTED/SHUTTING_DOWN
- **Circuit breaker**: `circuit_breaker:active` → 0/1
- **WebSocket connected**: `ws:connected` → 0/1
- **Deduplicación**: `closing:{position_id}` → previene cierre doble
- **Dead letter queue**: `notifications:dead_letter` → notificaciones fallidas

#### `security.py` — Autenticación
```
Cliente → Header "X-API-Key: tu_clave" → verify_api_key() → OK/401/403
```
- Sin key configurada + debug=True → acceso libre (dev mode)
- Sin key configurada + debug=False → error 500
- Key incorrecta → 403 Forbidden

#### `retry.py` — Reintentos con backoff exponencial
```
Intento 1 → falla → espera 1s
Intento 2 → falla → espera 2s
Intento 3 → falla → espera 4s
Intento 4 → falla → ERROR final
```
Se usa en `BinanceExecutor` para errores de red transitorios. NO reintenta errores permanentes (saldo insuficiente, símbolo inválido).

#### `notifications.py` — Alertas Telegram
Envía mensajes cuando:
- Se llena una orden
- Se activa stop-loss o take-profit
- Se activa el circuit breaker
- El sistema se detiene
- Hay una orden pendiente de aprobación
- El reconciler detecta problemas

Si Telegram falla, el mensaje va a una "dead letter queue" en Redis para inspección posterior.

#### `health.py` — Monitoreo de salud
Verifica cada 5 segundos:
- ¿PostgreSQL responde?
- ¿Redis responde?
- ¿Binance API responde? ¿Latencia < 2000ms?
- ¿WebSocket conectado?
- ¿Circuit breaker activo?

Si Redis o Exchange están caídos → **auto-halt del sistema**.

---

### 4.2 Domain (`app/domain/`)

Las reglas de negocio puras, sin dependencias externas.

#### `enums.py` — Estados posibles

```
SignalType:    BUY | SELL | HOLD
OrderStatus:   PENDING → SUBMITTED → SUBMITTING → FILLED
                                                 → PARTIALLY_FILLED
                                                 → CANCELLED
                                                 → REJECTED
PositionStatus: OPEN → CLOSED | STOPPED_OUT
ExecutionMode:  PAPER | LIVE
RiskAction:     APPROVE | REJECT | HALT_SYSTEM
```

#### `state_machine.py` — Transiciones válidas

Define qué cambios de estado son legales. Ejemplo:
- ✅ SUBMITTED → FILLED (orden se ejecutó)
- ✅ OPEN → STOPPED_OUT (SL activado)
- ❌ FILLED → PENDING (no se puede "des-ejecutar")
- ❌ STOPPED_OUT → OPEN (posición cerrada es final)

Si el código intenta una transición inválida, se lanza `InvalidStateTransitionError`.

---

### 4.3 Exchange (`app/exchange/`)

La conexión con Binance.

#### `binance_client.py` — REST API

```python
# Obtener precio actual
ticker = await client.get_ticker("BTCUSDT")
# → Ticker(symbol="BTCUSDT", price=50000, bid=49999, ask=50001)

# Obtener velas históricas
klines = await client.get_klines("BTCUSDT", "1h", limit=100)
# → [Kline(open=49000, high=50500, low=48900, close=50000, volume=1234), ...]

# Información del par
info = await client.get_exchange_info("BTCUSDT")
# → SymbolInfo(min_qty=0.00001, step_size=0.00001, min_notional=10)
```

**Cache**: Los precios se cachean en Redis por 5 segundos, las klines por 30 segundos, la info del exchange por 1 hora.

#### `binance_ws.py` — WebSocket (tiempo real)

```
Binance → wss://testnet.binance.vision/ws/btcusdt@bookTicker
       → {"s":"BTCUSDT", "b":"50000.00", "a":"50001.00"}
       → Cada ~100ms llega un precio nuevo
       → Se guarda en Redis: price:BTCUSDT
```

Si el WebSocket se desconecta:
1. Se marca `ws:connected=0` en Redis
2. Reconexión automática con backoff (1s, 2s, 4s... hasta 60s)
3. Si llega a 60s de delay → notificación Telegram
4. Position monitor detecta precios stale → auto-halt después de 5 consecutivos

---

### 4.4 Models (`app/models/`)

Los modelos de base de datos. Cada uno corresponde a una tabla en PostgreSQL.

#### `portfolio.py` — Tu cuenta

| Campo | Tipo | Descripción |
|-------|------|-------------|
| execution_mode | PAPER/LIVE | Qué portafolio es |
| total_balance | Decimal | Balance total (available + allocated) |
| available_balance | Decimal | Disponible para nuevas operaciones |
| allocated_balance | Decimal | Bloqueado en posiciones abiertas |
| total_pnl | Decimal | Ganancia/pérdida total acumulada |
| daily_pnl | Decimal | Ganancia/pérdida del día (se resetea) |
| max_drawdown | Decimal | Peor caída desde el máximo |

#### `signal.py` — Una señal de trading

| Campo | Tipo | Descripción |
|-------|------|-------------|
| symbol | String | BTCUSDT, ETHUSDT, etc. |
| signal_type | BUY/SELL | Dirección |
| confidence | Decimal | 0.0 a 1.0 (qué tan seguro está) |
| entry_price | Decimal | Precio sugerido de entrada |
| stop_loss | Decimal | Precio de pérdida máxima |
| take_profit | Decimal | Precio objetivo de ganancia |
| strategy_id | UUID | Qué estrategia la generó |
| indicators | JSON | RSI, SMA, ML probability, etc. |

#### `order.py` — Una orden al exchange

| Campo | Tipo | Descripción |
|-------|------|-------------|
| status | String | PENDING → SUBMITTING → FILLED |
| requested_qty | Decimal | Cantidad solicitada |
| filled_qty | Decimal | Cantidad efectivamente ejecutada |
| avg_fill_price | Decimal | Precio promedio de ejecución |
| exchange_order_id | String | ID de Binance (solo LIVE) |
| execution_mode | PAPER/LIVE | En qué modo se ejecutó |

#### `position.py` — Una posición abierta

| Campo | Tipo | Descripción |
|-------|------|-------------|
| symbol | String | BTCUSDT |
| side | LONG | Solo long para spot |
| entry_price | Decimal | Precio de compra |
| current_price | Decimal | Último precio conocido |
| quantity | Decimal | Cantidad de crypto |
| stop_loss | Decimal | Precio de salida por pérdida |
| take_profit | Decimal | Precio de salida por ganancia |
| unrealized_pnl | Decimal | Ganancia/pérdida no realizada |
| execution_mode | PAPER/LIVE | En qué modo se abrió |
| oco_order_id | String | ID del OCO en Binance (LIVE) |

#### `trade.py` — Un trade cerrado (histórico)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| entry_price | Decimal | Precio de entrada |
| exit_price | Decimal | Precio de salida |
| pnl | Decimal | Ganancia/pérdida en USD |
| pnl_percent | Decimal | Ganancia/pérdida en % |
| duration_seconds | Integer | Cuánto duró abierto |

---

## 5. Pipeline de Trading

El corazón del sistema. Está en `app/pipeline/` y tiene esta estructura:

```
Signal Engine → Strategy → Risk Manager → Capital Manager → Guard → Executor
     │              │           │              │              │         │
  "¿compro?"    "¿cuándo?"  "¿es seguro?"  "¿cuánto?"   "¿ahora?"  "¡compra!"
```

### 5.1 Signal Engine (`pipeline/signal_engine/`)

Genera señales de trading a partir de datos de mercado.

#### RSI (Relative Strength Index)
```
RSI mide: ¿El precio subió o bajó en los últimos N períodos?

RSI < 30 → Sobrevendido → El mercado "exageró" la caída → BUY
RSI > 70 → Sobrecomprado → El mercado "exageró" la subida → SELL
30-70    → Neutral → HOLD

Confidence = qué tan extremo es el RSI:
  RSI = 28 → confidence = 0.72 (moderada)
  RSI = 15 → confidence = 0.90 (muy alta)
```

#### SMA Crossover (Media Móvil Simple)
```
SMA rápida (9 períodos) vs SMA lenta (21 períodos)

SMA(9) cruza ARRIBA de SMA(21) → "Golden Cross" → BUY
SMA(9) cruza ABAJO de SMA(21) → "Death Cross" → SELL

Confidence = separación entre las SMAs:
  Cruce reciente, poca separación → 0.60
  Separación amplia → 0.80
```

#### Composite (combinación ponderada)
```
Señal final = RSI × 20% + SMA × 20% + ML × 60%

Ejemplo:
  RSI dice BUY con confidence 0.75
  SMA dice BUY con confidence 0.65
  ML dice BUY con confidence 0.80

  Resultado: BUY con confidence = 0.75×0.2 + 0.65×0.2 + 0.80×0.6 = 0.76
```

### 5.2 Strategy (`pipeline/strategy/`)

Transforma señales en intenciones de trading (TradeIntent).

#### MomentumStrategy
Usa CompositeSignalGenerator (RSI 40% + SMA 60%). Cuando la señal compuesta supera el threshold de confidence → genera TradeIntent con:
- entry_price = precio actual
- stop_loss = precio - 2%
- take_profit = precio + 4%

#### MLCompositeStrategy
Usa el modelo XGBoost como señal principal (60%) complementado con RSI (20%) y SMA (20%). El ML puede generar señales BUY o SELL.

#### StrategyRunner
Ejecuta múltiples estrategias en paralelo con timeout de 5 segundos. Si una estrategia falla 3 veces seguidas, se desactiva automáticamente.

### 5.3 Risk Manager (`pipeline/risk_manager/`)

Evalúa si un trade es seguro ANTES de ejecutarlo.

```
TradeIntent → [Regla 1] → [Regla 2] → [Regla 3] → [Regla 4] → [Regla 5] → APPROVED/REJECTED
```

#### Las 5 reglas de riesgo:

**1. MinConfidence (confidence mínimo)**
```
¿confidence >= 0.60?
Si NO → REJECT "Confidence too low"
```

**2. DailyLossLimit (límite de pérdida diaria)**
```
¿PnL del día > -3%?
Si NO → HALT_SYSTEM "Daily loss limit reached"
```
Si se activa, el circuit breaker detiene TODO el trading.

**3. MaxDrawdown (caída máxima desde el pico)**
```
¿drawdown actual < 10%?
Si NO → HALT_SYSTEM "Max drawdown exceeded"
```

**4. MaxPositions (máximo de posiciones abiertas)**
```
¿posiciones abiertas < 5?
Si NO → REJECT "Maximum positions reached"
```

**5. MaxExposure (exposición máxima por símbolo)**
```
¿exposición en BTCUSDT < 10% del portfolio?
Si NO → REJECT "Symbol exposure limit exceeded"
```

#### Circuit Breaker
Es el "botón de pánico" automático. Se activa cuando:
- DailyLossLimit o MaxDrawdown se violan
- Health check detecta falla crítica
- Runtime reconciler encuentra inconsistencias

Una vez activo, **nada puede operar** hasta que un humano lo resetee manualmente.

### 5.4 Capital Manager (`pipeline/capital_manager/`)

Calcula cuánto dinero poner en cada trade.

```
Fórmula:
  risk_amount = balance_disponible × risk_per_trade% × confidence
  distance = |entry_price - stop_loss| / entry_price
  position_value = risk_amount / distance
  quantity = position_value / entry_price

Ejemplo:
  Balance: $10,000
  Risk per trade: 1%
  Confidence: 0.75
  Entry: $50,000
  Stop loss: $49,000 (2% debajo)

  risk_amount = $10,000 × 0.01 × 0.75 = $75
  distance = 2%
  position_value = $75 / 0.02 = $3,750
  quantity = $3,750 / $50,000 = 0.075 BTC
```

**Límites:**
- Nunca exceder el balance disponible
- Nunca exceder 10% del total en un símbolo
- Mínimo $10 (mínimo de Binance)

### 5.5 Execution Guard (`pipeline/execution/guard.py`)

Última verificación antes de ejecutar, mirando condiciones de mercado en tiempo real.

```
✅ Price drift < 0.5%   → El precio no se movió demasiado desde la señal
✅ Spread < 0.3%         → La diferencia bid-ask es razonable
✅ Volume 24h > $100K    → Hay suficiente liquidez
✅ Precios positivos     → Sanity check básico
```

Si falla cualquiera → GUARD_REJECTED, el trade no se ejecuta.

### 5.6 Executor (`pipeline/execution/`)

Ejecuta la orden real.

#### PaperEngine (modo PAPER)
```python
# Simula un fill con slippage de 0.05%
fill_price = market_price × (1 + 0.0005)  # para BUY
fill_price = market_price × (1 - 0.0005)  # para SELL
```
No toca Binance. Todo es local.

#### BinanceExecutor (modo LIVE)
```python
# Envía orden MARKET real a Binance
result = await client.create_order(
    symbol="BTCUSDT",
    side="BUY",
    type="MARKET",
    quantity="0.075",
    newClientOrderId="TP-abc123..."  # idempotencia
)
```

**Protecciones:**
- Retry automático (3 intentos) para errores de red
- Reconciliación post-timeout: consulta Binance si la orden se ejecutó
- Estado SUBMITTING persistido en DB antes de enviar (sobrevive crashes)
- OCO order en Binance para SL/TP a nivel exchange

### 5.7 Orchestrator (`pipeline/orchestrator.py`)

El director de orquesta. Ejecuta los 12 pasos en secuencia:

```
 0. Validar SL/TP (stop_loss < entry < take_profit)
 1. Verificar sistema no halteado
 2. Bloquear portfolio (SELECT FOR UPDATE → previene race conditions)
 3. Risk Manager → 5 reglas
 4. Capital Manager → tamaño de posición
 5. Verificar balance suficiente
 6. Execution Guard → condiciones de mercado
 7. Persistir estado SUBMITTING (commit a disco)
 8. Executor → enviar orden
 9. Manejar partial fills
10. Position Manager → crear posición
10b. OCO order en Binance (solo LIVE)
11. Actualizar portfolio (SQL UPDATE atómico)
12. Registrar eventos
```

**Todo corre en una sola transacción de base de datos.** Si cualquier paso falla, todo se revierte.

---

## 6. Machine Learning

### 6.1 Pipeline de datos (`ml/data/`)

#### Downloader
Descarga datos históricos de Binance:
```
BTCUSDT 1h desde 2020-01-01 → ~50,000 velas
ETHUSDT 1h desde 2020-01-01 → ~50,000 velas
SOLUSDT, BNBUSDT...
```
Se guardan como archivos Parquet en `ml_data/raw/`.

#### Labeler (Triple Barrier)
Para cada vela, determina si fue una "buena compra":
```
Mirando las siguientes 12 horas:
  ¿El precio subió +2% antes de caer -1%? → Label = 1 (buena compra)
  ¿El precio cayó -1% antes de subir +2%? → Label = 0 (mala compra)
  ¿Ninguno en 12 horas?                   → Label = 0 (timeout)
```

### 6.2 Features (`ml/features/`)

Se calculan ~40 indicadores para cada vela:

| Categoría | Features | Descripción |
|-----------|----------|-------------|
| Técnicos | RSI(7), RSI(14), MACD, Bollinger Bands, ADX, ATR | Indicadores clásicos |
| Precio | Returns 1h/4h/24h, distance to high/low | Momentum y posición |
| Volumen | Volume MA, OBV slope, volume-price correlation | Actividad del mercado |
| Temporal | Hora del día, día de la semana | Patrones temporales |

### 6.3 Modelo XGBoost (`ml/training/`)

```
Input:  40 features de la vela actual
Output: Probabilidad de que sea "buena compra" (0.0 a 1.0)

Configuración anti-overfitting:
  max_depth: 4 (árboles poco profundos)
  min_child_weight: 5 (hojas con suficientes muestras)
  subsample: 0.8 (usa 80% de datos por árbol)
  colsample_bytree: 0.8 (usa 80% de features por árbol)
  early_stopping: 30 rounds sin mejora → para
```

### 6.4 Predicción en producción (`ml/serving/`)

#### Predictor
```python
should, direction, probability, features = predictor.should_trade(klines_df)
# should = True/False (¿operar?)
# direction = "BUY"/"SELL"/"HOLD"
# probability = 0.74 (confianza del modelo)
```

**Protecciones:**
- Si >10% de features son NaN → rechaza predicción
- Si modelo tiene >30 días → marcado como stale, no genera señales
- Si probabilidad entre 0.31 y 0.69 → HOLD (zona neutra)

#### Shadow Tracker
Monitorea las predicciones del ML sin ejecutarlas realmente. Compara "qué hubiera pasado" vs realidad. Útil para validar el modelo antes de confiar en él.

---

## 7. Sistema de Riesgo

### 7.1 Capas de protección

```
Capa 1: Risk Manager (5 reglas) → ANTES de ejecutar
Capa 2: Execution Guard → ANTES de enviar a Binance
Capa 3: Position Monitor (SL/TP) → DURANTE la posición
Capa 4: Circuit Breaker → EMERGENCIA
Capa 5: Runtime Reconciler → VERIFICACIÓN CONTINUA
Capa 6: Manual Halt (API) → HUMANO
```

### 7.2 Stop-Loss / Take-Profit

El Position Monitor corre cada 2-5 segundos:
```
Para cada posición abierta:
  1. Obtener precio actual de Redis
  2. Validar que el precio no sea stale (< 15 segundos)
  3. ¿precio <= stop_loss? → CERRAR (Stop Loss)
  4. ¿precio >= take_profit? → CERRAR (Take Profit)
```

**Protecciones:**
- `SELECT FOR UPDATE SKIP LOCKED` → previene cierre doble
- Deduplicación Redis (`closing:{id}` con TTL 30s)
- Precio stale → skip (no cierra con datos viejos)
- 5 precios stale consecutivos → auto-halt + Telegram alert
- En LIVE: OCO order en Binance como backup

### 7.3 Circuit Breaker

```
Estado normal: CLOSED → trading activo
                    │
                    ▼ (violación de riesgo)
              OPEN → todo bloqueado
                    │
                    ▼ (reset manual)
              CLOSED → trading reanuda
```

Se persiste en Redis Y en base de datos (tabla events). Si Redis se reinicia, el startup reconciler recupera el estado desde la DB.

---

## 8. Reconciliación y Seguridad

### 8.1 Startup Reconciler (una vez al arrancar)

Cuando el sistema inicia, verifica:
1. ¿Hay órdenes en estado SUBMITTING? → Consultar Binance si se ejecutaron
2. ¿El circuit breaker estaba activo? → Restaurar desde DB
3. ¿Redis dice SHUTTING_DOWN? → Limpiar a RUNNING

### 8.2 Runtime Reconciler (cada 30 segundos, solo LIVE)

El safety net más importante. Corre continuamente y verifica:

| Check | Qué busca | Acción |
|-------|-----------|--------|
| Stuck Orders | Órdenes SUBMITTING > 60s | Consulta Binance, corrige o cancela |
| Positions vs Exchange | Posiciones sin exchange_order_id | Alerta CRITICAL |
| Unknown Orders | Órdenes en Binance no en DB | Alerta CRITICAL |
| Balance Drift | Diferencia > 1% entre DB y Binance | Alerta WARNING |

Si detecta issues CRITICAL → **auto-halt** + notificación Telegram.

### 8.3 Estado SUBMITTING (protección contra crashes)

```
Flujo normal:
  Order = SUBMITTED → commit a DB → enviar a Binance → FILLED

¿Qué pasa si el proceso crashea?

SIN protección:
  Order = SUBMITTED → flush (no commit) → enviar a Binance → CRASH
  → Binance tiene la orden, DB no sabe → PLATA PERDIDA

CON protección (estado SUBMITTING):
  Order = SUBMITTING → COMMIT a disco → enviar a Binance → CRASH
  → Startup reconciler encuentra SUBMITTING → consulta Binance → recupera
```

### 8.4 Validación modo LIVE

El sistema se niega a arrancar en LIVE si:
- `API_KEY` está vacía
- `BINANCE_API_KEY` o `BINANCE_API_SECRET` están vacías
- `DEBUG=true` (nunca debug en producción)

---

## 9. Frontend Angular

### 9.1 Servicios

#### ApiService (`core/services/api.service.ts`)
```typescript
// Consume el backend
this.api.getPortfolio()        // GET /api/v1/portfolio
this.api.getOpenPositions()    // GET /api/v1/positions/open
this.api.getSignals()          // GET /api/v1/signals
this.api.getRiskStatus()       // GET /api/v1/risk/status
this.api.closePosition(id)     // POST /api/v1/positions/{id}/close
this.api.haltSystem()          // POST /api/v1/system/halt
```

#### WebSocketService (`core/services/websocket.service.ts`)
```typescript
// Recibe actualizaciones en tiempo real
ws://localhost:8000/ws?channels=portfolio,positions,signals,risk,system&token=API_KEY
```

### 9.2 Páginas

#### Dashboard
- Balance total, disponible, asignado
- PnL del día y total
- Posiciones abiertas con PnL en tiempo real
- Señales recientes
- Estado del sistema

#### Strategies
- Lista de estrategias (nombre, tipo, símbolos)
- Activar/desactivar estrategias
- Editar parámetros (RSI period, SMA fast/slow, etc.)

#### Trades
- Historial de trades cerrados
- PnL por trade
- Win rate, average win/loss

#### Risk Panel
- Estado del circuit breaker
- PnL diario vs límite
- Drawdown actual vs máximo permitido
- Posiciones abiertas vs máximo

---

## 10. Base de Datos

### 10.1 Tablas principales

```
portfolios    → 1 fila por modo (PAPER, LIVE)
signals       → Cada señal generada por las estrategias
orders        → Cada orden enviada (o simulada)
positions     → Posiciones abiertas y cerradas
trades        → Trades completados (con PnL)
events        → Log inmutable de todo lo que pasa
risk_configs  → Configuración de riesgo activa
strategy_configs → Estrategias registradas
kline_history → Velas históricas para ML
```

### 10.2 Constraints de seguridad (migración 006)

```sql
-- El balance asignado no puede exceder el total
CHECK (allocated_balance <= total_balance)

-- Stop loss debe estar debajo del entry (para LONG)
CHECK (side != 'LONG' OR stop_loss < entry_price)

-- Take profit debe estar arriba del entry (para LONG)
CHECK (side != 'LONG' OR take_profit > entry_price)

-- No se puede llenar más de lo pedido
CHECK (filled_qty IS NULL OR filled_qty <= requested_qty)
```

### 10.3 Migraciones

| # | Nombre | Qué hace |
|---|--------|----------|
| 001 | initial_schema | Crea todas las tablas |
| 002 | kline_history | Tabla para datos históricos ML |
| 003 | position_fixes | Agrega constraints básicos |
| 004 | fix_balance | Corrige balance >= 0 (no -1) |
| 005 | execution_mode | Agrega execution_mode y oco_order_id a positions |
| 006 | constraints_indexes | Constraints de seguridad + indexes de performance |

---

## 11. Configuración y Deployment

### 11.1 Variables de entorno (.env)

```bash
# === BÁSICO ===
DEBUG=false                          # true solo para desarrollo
EXECUTION_MODE=PAPER                 # PAPER o LIVE
API_KEY=tu_clave_secreta_aqui        # Protege los endpoints

# === BASE DE DATOS ===
DATABASE_URL=postgresql+asyncpg://user:pass@host:5434/trading_db

# === REDIS ===
REDIS_URL=redis://host:6381/0

# === BINANCE ===
BINANCE_API_KEY=                     # Tu API key de Binance
BINANCE_API_SECRET=                  # Tu API secret
BINANCE_TESTNET=true                 # true=testnet, false=producción real

# === PAPER TRADING ===
PAPER_INITIAL_BALANCE=10000.0        # Balance inicial simulado

# === RIESGO ===
RISK_MAX_DAILY_LOSS_PCT=0.03         # Máximo 3% pérdida diaria
RISK_MAX_DRAWDOWN_PCT=0.10           # Máximo 10% drawdown
RISK_MIN_CONFIDENCE=0.6              # Mínimo 60% confidence
RISK_MAX_POSITIONS=5                 # Máximo 5 posiciones abiertas
RISK_MAX_EXPOSURE_PER_SYMBOL_PCT=0.10 # Máximo 10% por símbolo
RISK_PER_TRADE_PCT=0.01              # Riesgo 1% por trade

# === GUARD ===
GUARD_MAX_PRICE_DRIFT_PCT=0.005      # Máximo 0.5% drift de precio
GUARD_MAX_SPREAD_PCT=0.003           # Máximo 0.3% spread
GUARD_MIN_VOLUME_24H=100000.0        # Mínimo $100K volumen 24h

# === NOTIFICACIONES ===
TELEGRAM_BOT_TOKEN=                  # Token de tu bot de Telegram
TELEGRAM_CHAT_ID=                    # ID del chat donde enviar alertas

# === CORS ===
CORS_ORIGINS=http://localhost:4200   # Orígenes permitidos (separados por coma)
```

### 11.2 Docker Compose

```bash
# Levantar todo
docker compose up -d

# Ver logs
docker compose logs -f app

# Parar
docker compose down
```

### 11.3 Comandos útiles

```bash
# Instalar dependencias
cd backend && pip install -e ".[dev]"

# Correr migraciones
PYTHONPATH=. alembic upgrade head

# Seed portfolio paper
PYTHONPATH=. python -m scripts.seed_paper_portfolio

# Arrancar API
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000

# Arrancar paper trading (background tasks)
PYTHONPATH=. python -m scripts.start_paper_trading

# Correr tests
PYTHONPATH=. pytest tests/ -v

# Entrenar modelo ML
PYTHONPATH=. python -m scripts.train_model

# Descargar datos históricos
PYTHONPATH=. python -m scripts.download_historical

# Backup de DB
./scripts/backup_db.sh
```

---

## 12. Glosario

| Término | Significado |
|---------|-------------|
| **SL (Stop Loss)** | Precio al que se cierra una posición para limitar pérdidas |
| **TP (Take Profit)** | Precio al que se cierra una posición para asegurar ganancias |
| **RSI** | Relative Strength Index — mide sobrecompra/sobreventa (0-100) |
| **SMA** | Simple Moving Average — promedio de precio de N períodos |
| **Golden Cross** | SMA rápida cruza arriba de SMA lenta (señal alcista) |
| **Death Cross** | SMA rápida cruza abajo de SMA lenta (señal bajista) |
| **Kline/Candlestick** | Una "vela" de precio: open, high, low, close, volume |
| **Slippage** | Diferencia entre precio esperado y precio real de ejecución |
| **Drawdown** | Caída del portfolio desde su punto más alto |
| **Sharpe Ratio** | Retorno ajustado por riesgo. > 1 es bueno, > 2 es excelente |
| **OCO Order** | "One Cancels Other" — orden de SL y TP simultáneas en Binance |
| **Circuit Breaker** | Mecanismo de emergencia que detiene todo el trading |
| **Paper Trading** | Trading simulado con dinero ficticio |
| **LIVE Trading** | Trading real con dinero real en Binance |
| **Reconciliación** | Verificar que la DB local coincide con el estado real en Binance |
| **Partial Fill** | Cuando una orden solo se ejecuta parcialmente |
| **Confidence** | Nivel de certeza de una señal (0.0 a 1.0) |
| **XGBoost** | Algoritmo de ML basado en gradient boosted trees |
| **Feature** | Variable/indicador que el ML usa para predecir |
| **Label** | Lo que el ML intenta predecir (buena compra = 1, mala = 0) |
| **Backtest** | Simular una estrategia sobre datos históricos |
| **Shadow Mode** | ML genera señales pero no se ejecutan (solo monitoreo) |
