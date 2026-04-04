export interface Portfolio {
  id: string;
  execution_mode: 'PAPER' | 'LIVE';
  total_balance: string;
  available_balance: string;
  allocated_balance: string;
  total_pnl: string;
  daily_pnl: string;
  max_drawdown: string;
  updated_at: string;
}

export type AssetClass = 'CRYPTO' | 'STOCKS';

export interface Signal {
  id: string;
  symbol: string;
  asset_class: AssetClass;
  signal_type: 'BUY' | 'SELL' | 'HOLD';
  confidence: string;
  timeframe: string;
  indicators: Record<string, any>;
  entry_price: string;
  stop_loss: string;
  take_profit: string;
  strategy_id: string;
  expires_at: string;
  created_at: string;
}

export interface Order {
  id: string;
  signal_id: string;
  symbol: string;
  asset_class: AssetClass;
  side: 'BUY' | 'SELL';
  order_type: 'MARKET' | 'LIMIT';
  status: string;
  requested_qty: string;
  filled_qty: string;
  requested_price: string;
  avg_fill_price: string | null;
  stop_loss: string;
  take_profit: string;
  execution_mode: 'PAPER' | 'LIVE';
  exchange_order_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Position {
  id: string;
  symbol: string;
  asset_class: AssetClass;
  side: 'LONG';
  status: 'OPEN' | 'PARTIALLY_CLOSED' | 'CLOSED' | 'STOPPED_OUT';
  entry_price: string;
  current_price: string;
  quantity: string;
  stop_loss: string;
  take_profit: string;
  unrealized_pnl: string;
  realized_pnl: string;
  opened_at: string;
  closed_at: string | null;
}

export interface Trade {
  id: string;
  position_id: string;
  symbol: string;
  asset_class: AssetClass;
  entry_price: string;
  exit_price: string;
  quantity: string;
  pnl: string;
  pnl_percent: string;
  signal_confidence: string;
  strategy_id: string;
  execution_mode: string;
  duration_seconds: number;
  opened_at: string;
  closed_at: string;
}

export type RiskProfileType = 'ULTRA_CONSERVADOR' | 'DEFENSIVO_AGRESIVO';

export interface RiskStatus {
  circuit_breaker_active: boolean;
  system_status: string;
  daily_pnl: string;
  daily_loss_limit: string;
  open_positions: number;
  max_positions: number;
  active_profile: RiskProfileType;
}

export interface RiskProfile {
  profile_type: RiskProfileType;
  min_confidence: string;
  max_positions: number;
  max_exposure_per_symbol_pct: string;
  risk_per_trade_pct: string;
  allow_partial_signal_agreement: boolean;
  min_agreeing_signals: number;
  use_atr_for_sl_tp: boolean;
  atr_period: number;
  atr_sl_multiplier: string;
  atr_tp_multiplier: string;
  max_daily_loss_pct: string;
  max_drawdown_pct: string;
}

export interface AlpacaStatus {
  enabled: boolean;
  market_open?: boolean;
  ws_connected?: boolean;
  stock_symbols?: string[];
}

export interface HealthStatus {
  status: string;
  system_status: string;
  checks: Record<string, { status: string; error?: string }>;
  alpaca?: AlpacaStatus;
  timestamp: string;
}

export interface WSMessage {
  channel: string;
  event: string;
  data: any;
  timestamp: string;
}
