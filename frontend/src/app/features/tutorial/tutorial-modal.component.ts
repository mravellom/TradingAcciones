import { Component, EventEmitter, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-tutorial-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './tutorial-modal.component.html',
  styleUrl: './tutorial-modal.component.scss',
})
export class TutorialModalComponent {
  @Output() close = new EventEmitter<void>();

  activeSection = 0;

  sections = [
    {
      title: 'Vista General',
      icon: '1',
      content: `
        <h3>Que es este sistema</h3>
        <p>Un bot de trading automatizado para <strong>criptomonedas (Binance)</strong> y <strong>acciones USA - S&amp;P 500, NASDAQ (Alpaca)</strong>. Analiza el mercado con indicadores tecnicos (RSI, SMA) y Machine Learning (XGBoost), toma decisiones de compra/venta, gestiona riesgo, y ejecuta operaciones de forma autonoma. Ambos mercados corren simultaneamente.</p>

        <h3>Stack Tecnologico</h3>
        <div class="tech-grid">
          <div class="tech-item"><span class="label">Backend</span> Python 3.11 + FastAPI</div>
          <div class="tech-item"><span class="label">Frontend</span> Angular 20 + TypeScript</div>
          <div class="tech-item"><span class="label">DB</span> PostgreSQL 16</div>
          <div class="tech-item"><span class="label">Cache</span> Redis 7</div>
          <div class="tech-item"><span class="label">Crypto</span> Binance API</div>
          <div class="tech-item"><span class="label">Stocks</span> Alpaca API</div>
          <div class="tech-item"><span class="label">ML</span> XGBoost + pandas</div>
        </div>
      `
    },
    {
      title: 'Arquitectura',
      icon: '2',
      content: `
        <h3>Diagrama de Componentes</h3>
        <pre class="diagram">
Frontend (Angular :4200)
    |  HTTP + WebSocket
Backend (FastAPI :8001)
    |
    +-- REST API (/api/v1/*)
    +-- WebSocket (/ws)
    +-- Background Tasks
    |       +-- Signal Scanner (60s)
    |       +-- Position Monitor (2-5s)
    |       +-- Runtime Reconciler (30s)
    |       +-- Daily Reset
    |
    +-- PIPELINE DE TRADING
    |   Signal -> Risk -> Capital -> Guard -> Execute
    |
    +--- Binance API (crypto 24/7)
    +--- Alpaca API (stocks 9:30-16:00 ET)
    +--- PostgreSQL (persistencia)
    +--- Redis (cache + estado)
        </pre>

        <h3>Flujo de Comunicacion</h3>
        <ul>
          <li><strong>Frontend -> Backend:</strong> HTTP REST para acciones, WebSocket para datos en tiempo real</li>
          <li><strong>Backend -> Binance:</strong> REST + WebSocket para crypto (24/7)</li>
          <li><strong>Backend -> Alpaca:</strong> REST + WebSocket para acciones USA (Lun-Vie 9:30-16:00 ET, con festivos)</li>
          <li><strong>Backend -> PostgreSQL:</strong> SQLAlchemy async para persistencia</li>
          <li><strong>Backend -> Redis:</strong> Cache de precios, estado del sistema, circuit breaker</li>
        </ul>
      `
    },
    {
      title: 'Flujo de Trading',
      icon: '3',
      content: `
        <h3>El ciclo completo: de senal a trade cerrado</h3>
        <div class="steps">
          <div class="step">
            <div class="step-num">1</div>
            <div class="step-content">
              <strong>Obtener datos</strong>
              <p>Binance (crypto) o Alpaca (stocks) envian velas historicas (open, high, low, close, volume)</p>
            </div>
          </div>
          <div class="step">
            <div class="step-num">2</div>
            <div class="step-content">
              <strong>Generar senal</strong>
              <p>RSI (sobrecompra/sobreventa) + SMA (golden/death cross) + ML XGBoost (40+ features) se combinan con pesos: ML 60%, RSI 20%, SMA 20%</p>
            </div>
          </div>
          <div class="step">
            <div class="step-num">3</div>
            <div class="step-content">
              <strong>Evaluar riesgo</strong>
              <p>5 reglas en secuencia: Min Confidence > 0.6, Daily Loss < 3%, Drawdown < 10%, Posiciones < 5, Exposicion por simbolo < 10%</p>
            </div>
          </div>
          <div class="step">
            <div class="step-num">4</div>
            <div class="step-content">
              <strong>Calcular tamano</strong>
              <p>Formula: risk_amount = balance x 1% x confidence. Position = risk_amount / SL_distance</p>
            </div>
          </div>
          <div class="step">
            <div class="step-num">5</div>
            <div class="step-content">
              <strong>Validar mercado</strong>
              <p>Execution Guard verifica con thresholds por mercado: Crypto (drift 0.5%, spread 0.3%, vol $100K) vs Stocks (drift 0.2%, spread 0.1%, vol $1M)</p>
            </div>
          </div>
          <div class="step">
            <div class="step-num">6</div>
            <div class="step-content">
              <strong>Ejecutar</strong>
              <p>Paper: simula fill (0.05% slippage crypto, 0.01% stocks). LIVE: orden real a Binance (crypto) o Alpaca (stocks)</p>
            </div>
          </div>
          <div class="step">
            <div class="step-num">7</div>
            <div class="step-content">
              <strong>Monitorear</strong>
              <p>Position Monitor (cada 2-5s) verifica SL/TP. Cuando el precio toca el limite, cierra automaticamente</p>
            </div>
          </div>
        </div>
      `
    },
    {
      title: 'Senales (RSI, SMA, ML)',
      icon: '4',
      content: `
        <h3>RSI (Relative Strength Index)</h3>
        <p>Mide si el precio subio o bajo en los ultimos N periodos (0-100).</p>
        <ul>
          <li><strong>RSI &lt; 30</strong> -> Sobrevendido -> BUY (el mercado exagero la caida)</li>
          <li><strong>RSI &gt; 70</strong> -> Sobrecomprado -> SELL (el mercado exagero la subida)</li>
          <li><strong>30-70</strong> -> Neutral -> HOLD</li>
        </ul>

        <h3>SMA Crossover (Media Movil Simple)</h3>
        <p>Compara SMA rapida (9 periodos) vs SMA lenta (21 periodos).</p>
        <ul>
          <li><strong>SMA(9) cruza ARRIBA de SMA(21)</strong> -> "Golden Cross" -> BUY</li>
          <li><strong>SMA(9) cruza ABAJO de SMA(21)</strong> -> "Death Cross" -> SELL</li>
        </ul>

        <h3>Machine Learning (XGBoost)</h3>
        <p>Modelo entrenado con 40+ features (RSI, MACD, ATR, volume, hora del dia, etc.) sobre datos historicos desde 2020.</p>
        <ul>
          <li>Input: 40 features de la vela actual</li>
          <li>Output: probabilidad de "buena compra" (0.0 a 1.0)</li>
          <li>Probabilidad &gt; 0.69 -> BUY</li>
          <li>Probabilidad &lt; 0.31 -> SELL</li>
          <li>Entre 0.31 y 0.69 -> HOLD</li>
        </ul>

        <h3>Combinacion (Composite)</h3>
        <p>Senal final = ML x 60% + RSI x 20% + SMA x 20%</p>

        <h3>Parametros por Mercado</h3>
        <table>
          <tr><th>Parametro</th><th>Crypto</th><th>Stocks</th></tr>
          <tr><td>RSI oversold/overbought</td><td>30 / 70</td><td>35 / 65</td></tr>
          <tr><td>SMA rapida / lenta</td><td>9 / 21</td><td>10 / 30</td></tr>
          <tr><td>Stop Loss</td><td>2%</td><td>1.5%</td></tr>
          <tr><td>Take Profit</td><td>4%</td><td>3%</td></tr>
        </table>
        <p>Las acciones son menos volatiles, por eso usan thresholds mas ajustados.</p>
      `
    },
    {
      title: 'Sistema de Riesgo',
      icon: '5',
      content: `
        <h3>6 Capas de Proteccion</h3>
        <div class="layers">
          <div class="layer layer-1"><span>1</span> Risk Manager (5 reglas) - ANTES de ejecutar</div>
          <div class="layer layer-2"><span>2</span> Execution Guard - ANTES de enviar a Binance</div>
          <div class="layer layer-3"><span>3</span> Position Monitor (SL/TP) - DURANTE la posicion</div>
          <div class="layer layer-4"><span>4</span> Circuit Breaker - EMERGENCIA automatica</div>
          <div class="layer layer-5"><span>5</span> Runtime Reconciler - VERIFICACION continua</div>
          <div class="layer layer-6"><span>6</span> Manual Halt (API) - Control HUMANO</div>
        </div>

        <h3>Las 5 Reglas de Riesgo</h3>
        <table>
          <tr><th>Regla</th><th>Condicion</th><th>Si falla</th></tr>
          <tr><td>Min Confidence</td><td>confidence >= 0.60</td><td>REJECT</td></tr>
          <tr><td>Daily Loss Limit</td><td>PnL dia > -3%</td><td>HALT SYSTEM</td></tr>
          <tr><td>Max Drawdown</td><td>drawdown < 10%</td><td>HALT SYSTEM</td></tr>
          <tr><td>Max Positions</td><td>posiciones < 5</td><td>REJECT</td></tr>
          <tr><td>Max Exposure</td><td>exposicion/simbolo < 10%</td><td>REJECT</td></tr>
        </table>

        <h3>Circuit Breaker</h3>
        <p>Boton de panico automatico. Se activa cuando se violan las reglas criticas (daily loss o max drawdown). Una vez activo, <strong>nada puede operar</strong> hasta que un humano lo resetee.</p>
      `
    },
    {
      title: 'Reconciliacion',
      icon: '6',
      content: `
        <h3>El problema que resuelve</h3>
        <p>Si Binance ejecuta una orden pero tu sistema crashea antes de guardarla en la DB, la plata esta en Binance pero el sistema no lo sabe. Sin reconciliacion = plata perdida.</p>

        <h3>Startup Reconciler (al arrancar)</h3>
        <ul>
          <li>Busca ordenes en estado SUBMITTING -> consulta Binance si se ejecutaron</li>
          <li>Recupera circuit breaker desde la DB (por si Redis se reinicio)</li>
          <li>Limpia estado SHUTTING_DOWN de Redis</li>
        </ul>

        <h3>Runtime Reconciler (cada 30s, solo LIVE)</h3>
        <table>
          <tr><th>Check</th><th>Que busca</th><th>Accion</th></tr>
          <tr><td>Stuck Orders</td><td>Ordenes SUBMITTING > 60s</td><td>Consulta Binance, corrige o cancela</td></tr>
          <tr><td>Positions vs Exchange</td><td>Posiciones sin exchange_order_id</td><td>Alerta CRITICAL</td></tr>
          <tr><td>Unknown Orders</td><td>Ordenes en Binance no en DB</td><td>Alerta CRITICAL</td></tr>
          <tr><td>Balance Drift</td><td>Diferencia > 1%</td><td>Alerta WARNING</td></tr>
        </table>
        <p>Si detecta issues CRITICAL -> <strong>auto-halt</strong> + notificacion Telegram.</p>

        <h3>Estado SUBMITTING</h3>
        <p>Antes de enviar a Binance, el sistema commitea el estado SUBMITTING a disco. Si crashea despues, el reconciler lo encuentra y lo recupera.</p>
      `
    },
    {
      title: 'Configuracion',
      icon: '7',
      content: `
        <h3>Modos de Ejecucion</h3>
        <table>
          <tr><th>Modo</th><th>Descripcion</th><th>Dinero real</th></tr>
          <tr><td>PAPER</td><td>Simulado, precios reales, operaciones ficticias</td><td>NO</td></tr>
          <tr><td>LIVE</td><td>Ordenes reales a Binance</td><td>SI</td></tr>
        </table>

        <h3>Variables Clave (.env)</h3>
        <table>
          <tr><th>Variable</th><th>Default</th><th>Descripcion</th></tr>
          <tr><td>EXECUTION_MODE</td><td>PAPER</td><td>PAPER o LIVE</td></tr>
          <tr><td>API_KEY</td><td>(vacio)</td><td>Protege los endpoints</td></tr>
          <tr><td>BINANCE_TESTNET</td><td>true</td><td>true=testnet, false=produccion</td></tr>
          <tr><td>ALPACA_ENABLED</td><td>false</td><td>Activa acciones USA</td></tr>
          <tr><td>ALPACA_API_KEY</td><td>(vacio)</td><td>API key de Alpaca</td></tr>
          <tr><td>STOCK_SYMBOLS</td><td>AAPL,MSFT...</td><td>Acciones a monitorear</td></tr>
          <tr><td>RISK_MAX_DAILY_LOSS_PCT</td><td>0.03</td><td>Maximo 3% perdida diaria</td></tr>
          <tr><td>RISK_MAX_POSITIONS</td><td>5</td><td>Maximo 5 posiciones</td></tr>
          <tr><td>RISK_PER_TRADE_PCT</td><td>0.01</td><td>1% riesgo por trade</td></tr>
        </table>

        <h3>Endpoints Utiles</h3>
        <table>
          <tr><th>Endpoint</th><th>Que hace</th></tr>
          <tr><td>GET /api/v1/system/health</td><td>Estado de salud del sistema</td></tr>
          <tr><td>GET /api/v1/portfolio</td><td>Balance actual</td></tr>
          <tr><td>GET /api/v1/positions/open</td><td>Posiciones abiertas</td></tr>
          <tr><td>GET /api/v1/system/reconciliation-status</td><td>Verificar consistencia</td></tr>
          <tr><td>POST /api/v1/system/halt</td><td>Detener trading</td></tr>
        </table>
      `
    },
    {
      title: 'Glosario',
      icon: '8',
      content: `
        <table class="glossary">
          <tr><td><strong>SL (Stop Loss)</strong></td><td>Precio al que se cierra una posicion para limitar perdidas</td></tr>
          <tr><td><strong>TP (Take Profit)</strong></td><td>Precio al que se cierra una posicion para asegurar ganancias</td></tr>
          <tr><td><strong>RSI</strong></td><td>Relative Strength Index - mide sobrecompra/sobreventa (0-100)</td></tr>
          <tr><td><strong>SMA</strong></td><td>Simple Moving Average - promedio de precio de N periodos</td></tr>
          <tr><td><strong>Golden Cross</strong></td><td>SMA rapida cruza arriba de SMA lenta (senal alcista)</td></tr>
          <tr><td><strong>Death Cross</strong></td><td>SMA rapida cruza abajo de SMA lenta (senal bajista)</td></tr>
          <tr><td><strong>Kline</strong></td><td>Una "vela" de precio: open, high, low, close, volume</td></tr>
          <tr><td><strong>Slippage</strong></td><td>Diferencia entre precio esperado y precio real de ejecucion</td></tr>
          <tr><td><strong>Drawdown</strong></td><td>Caida del portfolio desde su punto mas alto</td></tr>
          <tr><td><strong>Sharpe Ratio</strong></td><td>Retorno ajustado por riesgo. > 1 bueno, > 2 excelente</td></tr>
          <tr><td><strong>OCO Order</strong></td><td>One Cancels Other - SL y TP simultaneas en Binance</td></tr>
          <tr><td><strong>Circuit Breaker</strong></td><td>Mecanismo de emergencia que detiene todo el trading</td></tr>
          <tr><td><strong>Reconciliacion</strong></td><td>Verificar que la DB coincide con el estado real en Binance</td></tr>
          <tr><td><strong>Confidence</strong></td><td>Nivel de certeza de una senal (0.0 a 1.0)</td></tr>
          <tr><td><strong>XGBoost</strong></td><td>Algoritmo de ML basado en gradient boosted trees</td></tr>
          <tr><td><strong>Backtest</strong></td><td>Simular una estrategia sobre datos historicos</td></tr>
          <tr><td><strong>Asset Class</strong></td><td>Tipo de activo: CRYPTO (criptomonedas) o STOCKS (acciones USA)</td></tr>
          <tr><td><strong>Alpaca</strong></td><td>Broker/API gratuito para trading de acciones USA</td></tr>
          <tr><td><strong>Market Hours</strong></td><td>Horario del mercado USA: Lun-Vie 9:30-16:00 ET</td></tr>
          <tr><td><strong>S&amp;P 500</strong></td><td>Indice de las 500 empresas mas grandes de USA (SPY es su ETF)</td></tr>
        </table>
      `
    }
  ];

  onOverlayClick(event: MouseEvent): void {
    if ((event.target as HTMLElement).classList.contains('modal-overlay')) {
      this.close.emit();
    }
  }
}
