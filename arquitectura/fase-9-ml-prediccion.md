# Fase 9 — ML & Prediccion

> Arquitectura para incorporar Machine Learning al pipeline de trading.
> Fecha: 2026-03-20

---

## 1. Objetivo

Reemplazar (o complementar) el Signal Engine basado en reglas (RSI + SMA) con un modelo ML que responde a la pregunta:

**"Dado el estado actual del mercado, si abro un trade con este SL/TP, sera rentable?"**

NO predecimos precio. Predecimos **probabilidad de que el trade sea exitoso** alineado con nuestro risk management.

---

## 2. Los 5 Problemas Criticos

Estos problemas deben resolverse ANTES de escribir una linea de modelo. Si se ignoran, el modelo sera inutil en produccion.

### Problema 1 — Labeling (Triple Barrier Method)

```
MAL:   label = 1 si precio sube en la siguiente vela
BIEN:  label = 1 si precio toca TP antes de tocar SL dentro del horizonte temporal

Triple Barrier:
  - Barrera superior: Take Profit (+2% a +4%)
  - Barrera inferior: Stop Loss (-1% a -2%)
  - Barrera temporal: Timeout (12-24 horas)

Label:
  1 = precio toca TP primero
  0 = precio toca SL primero o timeout sin tocar ninguna
```

Esto alinea el label con el pipeline real (Risk Manager usa los mismos SL/TP).

### Problema 2 — Leakage

```
Reglas:
  - NUNCA normalizar con datos futuros
  - NUNCA hacer split random (siempre temporal)
  - CADA feature debe calcularse SOLO con info disponible en ese momento
  - Rolling window para todas las normalizaciones
  - Verificar: "si estuviera en tiempo real, tendria este dato?"
    Si la respuesta es no → es leakage

Ejemplos de leakage:
  MAL:   scaler.fit(todo_el_dataset)
  BIEN:  scaler.fit(datos_hasta_hoy)

  MAL:   train_test_split(shuffle=True)
  BIEN:  train=2020-2023, val=2024-Q1Q2, test=2024-Q3Q4

  MAL:   feature = (precio - min_historico) / (max_historico - min_historico)
  BIEN:  feature = (precio - rolling_min_90d) / (rolling_max_90d - rolling_min_90d)
```

### Problema 3 — Overfitting

```
Defensas en capas:
  1. Pocos features al inicio (10-15 max, no 200)
  2. Regularizacion fuerte (XGBoost: max_depth=4, min_child_weight=5, subsample=0.8)
  3. Walk-forward validation (no un solo split)
  4. Out-of-sample final (datos que NUNCA se tocan hasta la evaluacion final)
  5. Paper trading real (minimo 2 semanas antes de produccion)
  6. Gate obligatorio: si ML no supera baseline RSI+SMA, NO se usa
```

### Problema 4 — Metricas

```
NO usar:
  - Accuracy (un modelo que dice siempre HOLD tiene 90% accuracy)
  - F1 Score (no refleja PnL)
  - MSE/MAE (para regresion de precio, que no es nuestro caso)

SI usar:
  - Sharpe Ratio: retorno / volatilidad (>1.5 = bueno, >2.0 = excelente)
  - Profit Factor: sum(gains) / sum(losses) (>1.5 = bueno)
  - Max Drawdown: peor caida peak-to-trough (<10% = aceptable)
  - Expectancy: (win_rate * avg_win) - (loss_rate * avg_loss) (>0 = rentable)
  - Calmar Ratio: retorno anual / max drawdown (>2.0 = bueno)
  - Sortino Ratio: retorno / downside volatility (como Sharpe pero solo penaliza perdidas)
```

### Problema 5 — Frecuencia vs Ruido

```
1m  → 95% ruido. Solo para HFT con infra de microsegundos.
5m  → todavia mucho ruido para ML.
15m → empieza a haber patrones. Viable para modelos simples.
1h  → SWEET SPOT para crypto. Suficientes datos, menos ruido.
4h  → mas senal, menos trades. Bueno para confirmar tendencia.
1d  → poco ruido pero pocos datos para entrenar.

Decision: 1h como timeframe principal.
  - Features calculados en 1h
  - Features de apoyo en 4h y 1d (tendencia macro)
  - Labels con horizonte 12-24h
```

---

## 3. Arquitectura del Sistema ML

### 3.1 Estructura de Directorios

```
backend/
  app/
    ml/                                 # Todo el sistema ML
      __init__.py
      config.py                        # Hiperparametros, paths, feature lists
      |
      data/                            # Ingestion y preparacion
        __init__.py
        downloader.py                  # Descarga OHLCV historico de Binance
        feature_store.py               # Almacena features calculados
        labeler.py                     # Triple Barrier Labeling
      |
      features/                        # Feature engineering
        __init__.py
        technical.py                   # RSI, MACD, Bollinger, ATR, OBV, etc.
        price_action.py                # Returns, volatilidad, gaps
        volume.py                      # Volume profile, VWAP, relative volume
        temporal.py                    # Hora, dia semana, mes
        multi_timeframe.py             # Features de 4h y 1d
        pipeline.py                    # Orquesta calculo de features (sin leakage)
      |
      models/                          # Modelos ML
        __init__.py
        base.py                        # Interface abstracta MLModel
        xgboost_model.py              # XGBoost classifier
        lstm_model.py                  # LSTM (fase posterior)
        registry.py                    # Model versioning + loading
      |
      training/                        # Entrenamiento
        __init__.py
        trainer.py                     # Orquesta training pipeline
        splitter.py                    # Walk-forward temporal splits
        evaluator.py                   # Metricas de trading (Sharpe, PF, DD)
      |
      backtesting/                     # Backtester
        __init__.py
        engine.py                      # Motor de backtesting
        simulator.py                   # Simula ejecucion con slippage/comisiones
        report.py                      # Genera reportes de backtest
      |
      serving/                         # Modelo en produccion
        __init__.py
        predictor.py                   # Carga modelo y genera predicciones
        ml_signal_generator.py         # SignalGenerator que usa ML
      |
    pipeline/
      signal_engine/
        ml_generator.py                # NUEVO: wrapper que usa ml/serving/

  ml_data/                             # Datos (fuera de app/, gitignored)
    raw/                               # OHLCV descargado
    processed/                         # Features calculados
    models/                            # Modelos entrenados (.pkl, .pt)
    experiments/                       # Logs de MLflow
    backtest_results/                  # Reportes de backtests

  scripts/
    download_historical.py             # Descarga datos de Binance
    train_model.py                     # Entrena modelo
    run_backtest.py                    # Ejecuta backtest
    evaluate_model.py                  # Compara modelo vs baseline
```

### 3.2 Dependencias Adicionales

```toml
# En pyproject.toml [project.optional-dependencies]
ml = [
    "scikit-learn>=1.4.0",
    "xgboost>=2.0.0",
    "lightgbm>=4.3.0",
    "torch>=2.2.0",           # Solo para LSTM (paso 9E+)
    "mlflow>=2.11.0",
    "optuna>=3.5.0",          # Hyperparameter tuning
    "shap>=0.44.0",           # Feature importance / explicabilidad
    "vectorbt>=0.26.0",       # Backtesting rapido (opcional)
]
```

---

## 4. Triple Barrier Labeling — Detalle

### Algoritmo

```
Para cada vela en el dataset:
  1. Definir entry_price = close de la vela actual
  2. Definir:
     - upper_barrier = entry_price * (1 + tp_pct)    # ej: +2%
     - lower_barrier = entry_price * (1 - sl_pct)    # ej: -1%
     - time_barrier  = N velas hacia adelante         # ej: 12 velas de 1h
  3. Recorrer las siguientes N velas:
     - Si high >= upper_barrier → label = 1 (TP hit first)
     - Si low  <= lower_barrier → label = 0 (SL hit first)
  4. Si ninguna barrera se toca → label = 0 (timeout, no rentable)
```

### Parametros Configurables

```python
@dataclass
class LabelConfig:
    tp_pct: float = 0.02          # Take Profit %
    sl_pct: float = 0.01          # Stop Loss %
    horizon_bars: int = 12        # Maximo de velas a mirar
    timeframe: str = "1h"         # Timeframe base
    min_samples_per_class: int = 100  # Minimo para evitar class imbalance
```

### Variantes

```
Variante 1 — Binario:
  1 = TP hit, 0 = SL hit o timeout

Variante 2 — Ternario:
  1 = TP hit, 0 = timeout, -1 = SL hit

Variante 3 — Continuo:
  label = max_favorable_excursion / (max_favorable_excursion + max_adverse_excursion)
  Rango [0, 1], donde >0.5 = trade favorable

Recomendacion: empezar con Variante 1 (binario). Simple, alineado con pipeline.
```

---

## 5. Feature Engineering — Sin Leakage

### 5.1 Features Tecnicos (calculados en 1h)

```
Grupo 1 — Momentum (5 features):
  - RSI(14)
  - RSI(7)  — RSI rapido
  - MACD_histogram
  - MACD_signal_cross (1 si MACD cruzo signal recientemente)
  - Stochastic %K

Grupo 2 — Tendencia (4 features):
  - SMA(9) / SMA(21) ratio
  - EMA(12) / EMA(26) ratio
  - ADX(14) — fuerza de tendencia
  - Precio vs SMA(50) — distancia porcentual

Grupo 3 — Volatilidad (3 features):
  - ATR(14) / precio — volatilidad normalizada
  - Bollinger Band width
  - Rolling std(20) / precio

Grupo 4 — Volumen (3 features):
  - Volume / SMA_volume(20) — volumen relativo
  - OBV_slope(10) — pendiente de On-Balance Volume
  - Volume_price_trend — correlacion precio-volumen reciente

Total: 15 features base
```

### 5.2 Features Multi-Timeframe

```
De 4h:
  - RSI(14) en 4h
  - Tendencia SMA(9)/SMA(21) en 4h
  - ATR(14) en 4h

De 1d:
  - RSI(14) en 1d
  - Precio vs SMA(50) en 1d

Total: 5 features adicionales
```

### 5.3 Features Temporales

```
  - hour_sin, hour_cos (encoding ciclico de hora UTC)
  - day_of_week_sin, day_of_week_cos

Total: 4 features
```

### 5.4 Features Derivados

```
  - Return 1h, 4h, 24h (ultimos retornos)
  - Drawdown actual (distancia del precio al max de las ultimas 24h)

Total: 4 features
```

### Total: 28 features

Se empiezan con los 15 base. Se agregan los demas solo si mejoran el modelo en validacion.

### 5.5 Reglas Anti-Leakage

```python
class FeaturePipeline:
    """Calcula features respetando causalidad temporal."""

    def compute(self, df: pd.DataFrame, current_idx: int) -> dict:
        """Solo usa datos hasta current_idx (inclusive)."""
        window = df.iloc[:current_idx + 1]  # NUNCA current_idx + N

        features = {}
        features["rsi_14"] = self._rsi(window.close, 14)
        features["sma_ratio"] = self._sma(window.close, 9) / self._sma(window.close, 21)
        # ... etc

        # Normalizacion con rolling window (no global)
        for key, val in features.items():
            roll = window[key].rolling(90)  # 90 periodos de contexto
            features[f"{key}_norm"] = (val - roll.mean()) / (roll.std() + 1e-8)

        return features
```

---

## 6. Modelo XGBoost — Configuracion

### 6.1 Hiperparametros Base (anti-overfitting)

```python
xgb_params = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "max_depth": 4,                 # Poco profundo = menos overfitting
    "min_child_weight": 5,          # Requiere mas muestras por hoja
    "subsample": 0.8,               # No usar 100% de los datos por arbol
    "colsample_bytree": 0.8,        # No usar 100% de features por arbol
    "learning_rate": 0.05,          # Lento pero estable
    "n_estimators": 500,            # Con early_stopping
    "reg_alpha": 0.1,               # L1 regularization
    "reg_lambda": 1.0,              # L2 regularization
    "scale_pos_weight": 1.0,        # Ajustar si hay class imbalance
    "random_state": 42,
}
```

### 6.2 Training Pipeline

```
1. Cargar datos historicos (OHLCV 1h, 2020-2025)
2. Calcular features (sin leakage)
3. Calcular labels (triple barrier)
4. Walk-forward split:
   Fold 1: Train 2020-2022 → Val 2023-Q1
   Fold 2: Train 2020-2023Q1 → Val 2023-Q2Q3
   Fold 3: Train 2020-2023Q3 → Val 2024-Q1Q2
   Fold 4: Train 2020-2024Q2 → Val 2024-Q3Q4
   Test final: 2025 (NUNCA tocado durante training)
5. Entrenar XGBoost en cada fold
6. Evaluar con metricas de trading (no accuracy)
7. Si pasa el gate → deploy
```

### 6.3 Output del Modelo

```python
# El modelo NO reemplaza la senal, la ENRIQUECE
class MLSignalGenerator(SignalGenerator):
    """Signal generator que usa modelo ML."""

    @property
    def name(self) -> str:
        return "ml_xgboost"

    async def generate(self, symbol: str, klines: list[Kline]) -> SignalResult | None:
        # 1. Calcular features
        features = self.feature_pipeline.compute(klines)

        # 2. Predecir probabilidad
        probability = self.model.predict_proba(features)  # 0.0 - 1.0

        # 3. Solo generar senal si probabilidad > umbral
        if probability < self.min_probability:  # ej: 0.55
            return None

        # 4. Mapear probabilidad a confidence
        #    0.55 → confidence 0.6
        #    0.75 → confidence 0.85
        confidence = self._map_to_confidence(probability)

        # 5. Calcular SL/TP basado en ATR
        atr = features["atr_14"]
        entry = klines[-1].close
        stop_loss = entry - (atr * Decimal("1.5"))
        take_profit = entry + (atr * Decimal("3.0"))  # ratio 2:1

        return SignalResult(
            symbol=symbol,
            signal_type=SignalType.BUY,
            confidence=confidence,
            indicators={
                "ml_probability": float(probability),
                "model_version": self.model_version,
                **{k: float(v) for k, v in features.items()},
            },
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
```

---

## 7. Backtesting Engine

### 7.1 Arquitectura

```
BacktestEngine:
  Input:
    - Datos historicos (OHLCV)
    - Modelo entrenado (o estrategia basada en reglas)
    - Config (capital inicial, comisiones, slippage)

  Proceso:
    Para cada vela:
      1. Calcular features (solo con datos pasados)
      2. Generar senal (modelo o regla)
      3. Pasar por Risk Manager (mismo que produccion)
      4. Pasar por Capital Manager (mismo que produccion)
      5. Simular ejecucion (precio + slippage + comision)
      6. Gestionar posiciones (SL/TP check)
      7. Registrar trade si se cierra

  Output:
    - Lista de trades simulados
    - Equity curve
    - Metricas: Sharpe, Sortino, PF, DD, Calmar, Expectancy
    - Comparacion vs buy-and-hold
    - Comparacion vs baseline (RSI+SMA)
```

### 7.2 Parametros de Simulacion

```python
@dataclass
class BacktestConfig:
    initial_capital: Decimal = Decimal("10000")
    commission_pct: Decimal = Decimal("0.001")    # 0.1% Binance spot
    slippage_pct: Decimal = Decimal("0.0005")     # 0.05%
    max_positions: int = 5
    risk_per_trade_pct: Decimal = Decimal("0.01") # 1%
    timeframe: str = "1h"
```

### 7.3 Walk-Forward Validation

```
No es un solo backtest. Son N backtests secuenciales.

          Train          Val      Test
Fold 1: |====2020-2022====|==2023Q1==|
Fold 2: |=====2020-2023Q1=====|==2023Q2Q3==|
Fold 3: |======2020-2023Q3======|==2024Q1Q2==|
Fold 4: |=======2020-2024Q2=======|==2024Q3Q4==|

Out-of-sample final: 2025 (NUNCA tocado)

Cada fold:
  1. Entrena modelo en Train
  2. Evalua en Val
  3. Registra metricas

Modelo final:
  - Entrena en todo (2020-2024)
  - Evalua en OOS (2025)
  - Si pasa → produccion
```

---

## 8. Gate de Produccion (Obligatorio)

Antes de activar el modelo ML en el pipeline real, debe superar TODOS estos gates:

```
Gate 1 — Backtest Walk-Forward:
  - Sharpe Ratio > 1.0 en TODOS los folds (no solo promedio)
  - Profit Factor > 1.3 en TODOS los folds
  - Max Drawdown < 15% en TODOS los folds

Gate 2 — Out-of-Sample:
  - Sharpe > 1.0 en datos 2025
  - Profit Factor > 1.3
  - Max Drawdown < 15%

Gate 3 — Baseline Comparison:
  - ML debe superar a RSI+SMA en Sharpe Y en Profit Factor
  - Si no supera → NO se usa ML, se queda con reglas

Gate 4 — Paper Trading:
  - Minimo 2 semanas en paper con datos en vivo
  - Metricas deben ser consistentes con backtest (+/- 20%)
  - Si divergen mucho → posible overfitting, volver a entrenar

Gate 5 — Gradual Rollout:
  - Semana 1-2: ML genera senales pero NO ejecuta (shadow mode)
  - Semana 3-4: ML ejecuta con 25% del capital
  - Semana 5+: Si todo bien, escalar a 100%
```

---

## 9. Integracion con Pipeline Existente

### 9.1 ML como nuevo SignalGenerator

```
El modelo ML se integra como UN GENERADOR MAS en el CompositeSignalGenerator:

CompositeSignalGenerator:
  generators:
    - RSISignalGenerator      peso: 0.2  (sigue activo como baseline)
    - SMASignalGenerator      peso: 0.2  (sigue activo como baseline)
    - MLSignalGenerator       peso: 0.6  (nuevo, peso mayor)

El composite requiere ACUERDO entre generadores.
Si ML dice BUY pero RSI dice neutral → no opera.
Esto es una capa extra de seguridad.
```

### 9.2 Alternativa: ML reemplaza todo

```
Si el modelo ML demuestra ser consistentemente superior (Gate 3):

CompositeSignalGenerator:
  generators:
    - MLSignalGenerator       peso: 1.0

Pero SOLO despues de superar todos los gates.
```

### 9.3 El pipeline NO cambia

```
Signal Engine (ahora con ML)
     |
Strategy Runner (isolation, timeout, auto-deactivate)
     |
Risk Manager (MISMAS 5 reglas, sin cambios)
     |
Capital Manager (MISMO sizing, sin cambios)
     |
Execution Guard (MISMO, sin cambios)
     |
Executor (paper o Binance)
     |
Position Manager + Trade Tracker
```

El ML SOLO cambia la generacion de senales. Todo el risk management, capital management y execution siguen exactamente igual. Esto es intencional: el ML no puede bypasear las protecciones.

---

## 10. LSTM / Transformer (Fase Posterior)

Solo si XGBoost pasa todos los gates y queremos mas capacidad.

### 10.1 LSTM

```
Arquitectura:
  Input:  secuencia de 48-168 velas (2-7 dias de 1h)
  Shape:  (batch, seq_len, num_features)  → (32, 168, 28)

  Capas:
    LSTM(hidden=64, layers=2, dropout=0.3)
    Linear(64 → 32)
    ReLU
    Linear(32 → 1)
    Sigmoid → probabilidad [0, 1]

  Training:
    Loss: BCELoss (binary cross entropy)
    Optimizer: Adam(lr=1e-4)
    Early stopping en validation loss
    Batch size: 32
    Epochs: max 100 (con early stop suele terminar en 20-30)
```

### 10.2 Temporal Fusion Transformer (TFT)

```
Ventajas sobre LSTM:
  - Atencion temporal: sabe que velas del pasado son mas importantes
  - Variables estaticas: puede usar symbol como input
  - Interpretabilidad: muestra que features y que periodos influyeron
  - Mejor con variables exogenas (sentiment, on-chain)

Desventaja:
  - Mas complejo de implementar
  - Requiere mas datos para entrenar bien

Libreria: pytorch-forecasting (wrapper sobre PyTorch)
```

---

## 11. Datos Externos (Fase Posterior)

### 11.1 Sentiment

```
Fear & Greed Index:
  - API: alternative.me (gratis)
  - Feature: valor 0-100, actualizado diario
  - Uso: extremos (<20 o >80) como confirmacion

Twitter/X Sentiment:
  - API: X API v2 (basic tier ~$100/mes)
  - Analisis: contar menciones + sentiment (VADER o finBERT)
  - Feature: sentiment_score rolling 24h

CryptoPanic News:
  - API: gratis (rate limited)
  - Feature: news_sentiment_24h, news_volume_24h
```

### 11.2 On-Chain

```
Proveedor: Glassnode o CryptoQuant (~$40-80/mes)

Features:
  - Exchange net flow (inflow - outflow): predictor de presion vendedora
  - Active addresses: proxy de actividad de red
  - MVRV ratio: Market Value / Realized Value
  - Whale transaction count (>$1M)

Estos datos son mas lentos (actualizacion diaria o cada pocas horas)
pero aportan informacion que el precio solo no tiene.
```

---

## 12. Costos Estimados

### Minimo Viable (solo XGBoost)

| Item | Costo |
|------|-------|
| Datos OHLCV Binance | Gratis |
| Python ML stack | Gratis |
| MLflow (self-hosted) | Gratis |
| Training en CPU | Gratis (laptop) |
| **Total** | **$0/mes** |

### Completo (LSTM + datos externos)

| Item | Costo |
|------|-------|
| Datos OHLCV | Gratis |
| GPU cloud (training) | $10-50/mes |
| Glassnode/CryptoQuant | $40-80/mes |
| X API (sentiment) | $100/mes |
| MLflow (self-hosted) | Gratis |
| **Total** | **$150-230/mes** |

---

## 13. Plan de Implementacion

| Paso | Que | Tiempo | Prerequisitos |
|------|-----|--------|---------------|
| **9A** | Descarga datos historicos OHLCV 1h (2020-2025) para BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT | 2-3 dias | Binance API |
| **9B** | Triple Barrier Labeling con config alineada al SL/TP del pipeline | 2-3 dias | Paso 9A |
| **9C** | Feature engineering (15 features base, anti-leakage) | 4-5 dias | Paso 9B |
| **9D** | Backtesting engine con walk-forward + metricas de trading | 5-7 dias | Paso 9C |
| **9E** | XGBoost model + training pipeline + MLflow tracking | 4-5 dias | Paso 9D |
| **9F** | Validar XGBoost vs RSI+SMA baseline en backtester | 2-3 dias | Paso 9E |
| **9G** | Gate evaluation (todos los gates deben pasar) | 1-2 dias | Paso 9F |
| **9H** | MLSignalGenerator: integrar modelo al pipeline como SignalGenerator | 2-3 dias | Paso 9G |
| **9I** | Shadow mode: ML genera senales sin ejecutar (2 semanas minimo) | 14 dias | Paso 9H |
| **9J** | Si shadow mode es consistente: activar con 25% capital | 7 dias | Paso 9I |
| **9K** | (Opcional) LSTM si XGBoost es insuficiente | 2-3 semanas | GPU, paso 9F |
| **9L** | (Opcional) Sentiment + on-chain features | 1-2 semanas | APIs externas |

**Tiempo total minimo (hasta 9J): ~6-8 semanas**
**Tiempo total completo (hasta 9L): ~12-14 semanas**

---

## 14. Reglas de Oro

```
1. LABELING CORRECTO antes que features
   → Triple Barrier alineado con SL/TP real

2. CERO LEAKAGE
   → Todo rolling, todo temporal, todo causal

3. METRICAS DE TRADING, no de ML
   → Sharpe, Profit Factor, Drawdown, Expectancy

4. GATE OBLIGATORIO
   → Si ML no supera baseline, no se usa. Punto.

5. GRADUAL ROLLOUT
   → Shadow → 25% → 50% → 100%. Nunca directo.

6. EL RISK MANAGER NO SE TOCA
   → ML cambia senales, no protecciones

7. SIMPLE PRIMERO
   → XGBoost con 15 features antes de LSTM con 200 features

8. BACKTEST ≠ REALIDAD
   → Paper trading real es la prueba final

9. REENTRENAR PERIODICAMENTE
   → El mercado cambia. Modelo de hace 6 meses puede ser obsoleto.
   → Reentrenar mensual o cuando metricas degraden >20%

10. DOCUMENTAR TODO
    → Cada experimento en MLflow. Cada decision con razon.
```
