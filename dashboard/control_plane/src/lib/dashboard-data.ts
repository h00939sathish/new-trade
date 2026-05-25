export interface PaperSummary {
  portfolio_value: number;
  cash: number;
  holdings_value: number;
  peak_value: number;
  initial_capital: number;
  total_return_pct: number;
  day_pnl: number;
  open_positions: number;
  total_trades: number;
  win_rate_pct: number;
}

export interface PaperOrderHistoryItem {
  order_ref: string;
  symbol: string;
  side: string;
  quantity: number;
  status: string;
  broker_order_id?: string | null;
  strategy?: string | null;
  error_message?: string | null;
  created_at?: string | null;
}

export interface PaperPosition {
  symbol: string;
  shares: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  weight: number;
}

export interface PaperEquityPoint {
  timestamp: string;
  portfolio_value: number;
  cash: number;
  holdings_value: number;
  num_positions: number;
}

export interface PaperTrade {
  symbol: string;
  action: string;
  shares: number;
  price: number;
  execution_price: number;
  slippage: number;
  commission: number;
  strategy?: string | null;
  pnl: number;
  timestamp: string;
}

export interface PaperAlert {
  timestamp?: string;
  source_agent?: string;
  payload?: Record<string, unknown>;
}

export interface BrokerHealthSnapshot {
  available?: boolean;
  status?: string;
  consecutive_failures?: number;
  last_error?: string | null;
  last_failure_at?: string | null;
  wrapped_broker?: string | null;
  context?: string | null;
  alert?: string | null;
  alert_timestamp?: string | null;
}

export interface ReconciliationSnapshot {
  matched?: boolean;
  broker?: string | null;
  cash_delta?: number | null;
  portfolio_value_delta?: number | null;
  positions_only_local?: string[];
  positions_only_broker?: string[];
  share_deltas?: Record<string, { local?: number; broker?: number; delta?: number }>;
  local_cash_before?: number | null;
  broker_cash?: number | null;
  local_value_before?: number | null;
  broker_value?: number | null;
  synced_at?: string | null;
  alert?: string | null;
  alert_timestamp?: string | null;
}

export interface PaperReport {
  generated_at: string;
  source?: 'paper' | 'live';
  summary: PaperSummary;
  orders: {
    status_counts: Record<string, number>;
    recent: PaperOrderHistoryItem[];
  };
  positions: PaperPosition[];
  equity_curve: PaperEquityPoint[];
  recent_trades: PaperTrade[];
  recent_alerts: PaperAlert[];
  broker_health?: BrokerHealthSnapshot;
  reconciliation?: ReconciliationSnapshot;
}

export interface ValidationStrategyParticipation {
  strategy: string;
  trades: number;
  gross_value: number;
  avg_confidence: number;
}

export interface ValidationRegime {
  regime: string;
  days: number;
  avg_daily_return_pct: number;
  avg_turnover_pct?: number;
}

export interface ValidationMonthlyReturn {
  month: string;
  return_pct: number;
}

export interface ValidationReport {
  summary?: {
    total_return?: number;
    annual_return?: number;
    max_drawdown?: number;
    sharpe_ratio?: number;
    volatility?: number;
    total_trades?: number;
    final_value?: number;
    initial_capital?: number;
    benchmark_return?: number;
    alpha?: number;
  };
  benchmark_comparison?: {
    strategy_total_return_pct?: number;
    benchmark_total_return_pct?: number;
    alpha_pct?: number;
    final_strategy_value?: number;
    final_benchmark_value?: number;
  };
  trading_efficiency?: {
    total_turnover?: number;
    turnover_ratio?: number;
    avg_trade_value?: number;
    median_trade_value?: number;
    total_slippage?: number;
    total_commission?: number;
    cost_drag_pct_of_initial?: number;
  };
  monthly_returns?: ValidationMonthlyReturn[];
  strategy_participation?: ValidationStrategyParticipation[];
  regime_breakdown?: ValidationRegime[];
  configuration?: {
    benchmark?: string;
    symbols?: string[];
    portfolio?: {
      method?: string;
      initial_capital?: number;
      max_positions?: number;
      rebalance_frequency?: string;
    };
    risk_management?: {
      max_position_pct?: number;
      max_sector_exposure_pct?: number;
      max_drawdown_pct?: number;
      drawdown_reduction?: number;
      atr_volatility_multiple?: number;
      stop_loss_pct?: number;
      take_profit_pct?: number;
    };
    strategies?: Record<string, Record<string, unknown> & { enabled?: boolean; weight?: number }>;
  };
}

export interface AnalysisSentiment {
  score: number;
  magnitude: number;
}

export interface AnalysisFundamental {
  value_score?: number;
  growth_score?: number;
}

export interface SkillInsight {
  technical_outlook?: string;
  valuation?: string;
  recommendationMean?: number;
  targetMeanPrice?: number;
  currentPrice?: number;
  earningsGrowth?: number;
  revenueGrowth?: number;
  profitMargins?: number;
}

export interface AnalysisResults {
  timestamp?: string;
  market_data_symbols?: string[];
  features_computed?: boolean;
  sentiment?: Record<string, AnalysisSentiment>;
  fundamentals_internal?: Record<string, AnalysisFundamental>;
  fundamentals_skill?: {
    payload?: Record<string, { insights?: SkillInsight }>;
  };
}

export interface ExperimentRankingItem {
  name: string;
  score?: number;
  metrics?: {
    total_return?: number;
    annual_return?: number;
    max_drawdown?: number;
    sharpe_ratio?: number;
    volatility?: number;
    total_trades?: number;
    final_value?: number;
    initial_capital?: number;
    benchmark_return?: number;
    alpha?: number;
  };
  validation_excerpt?: {
    turnover_ratio?: number;
    cost_drag_pct_of_initial?: number;
    sideways_avg_daily_return_pct?: number;
  };
  config_overrides?: {
    signal_aggregation?: Record<string, unknown>;
    strategies?: Record<string, Record<string, unknown>>;
  };
}

export interface ExperimentReport {
  generated_at?: string;
  objective?: {
    name?: string;
    formula?: string;
  };
  experiments_run?: number;
  successful_experiments?: number;
  ranking?: ExperimentRankingItem[];
  best_experiment?: ExperimentRankingItem;
}

export interface PendingOrder {
  id: number;
  symbol: string;
  action: string;
  quantity: number;
  price: number;
  status: string;
  order_type?: string;
  confidence?: number;
  rationale?: string;
  thesis?: string;
  risk_score?: number;
  created_at?: string;
  processed_at?: string | null;
  notes?: string;
}

export interface OrderListResponse {
  orders: PendingOrder[];
  total: number;
}

export interface StrategyRuntimeActivity {
  recent_trades?: number;
  gross_pnl?: number;
  wins?: number;
  losses?: number;
  total_slippage?: number;
  total_commission?: number;
  last_trade_at?: string | null;
  win_rate_pct?: number;
  top_symbols?: Array<[string, number]>;
}

export interface StrategyDrilldownEntry {
  name: string;
  enabled: boolean;
  configured_weight: number;
  runtime_weight: number;
  validation?: {
    strategy?: string;
    trades?: number;
    gross_value?: number;
    avg_confidence?: number;
  };
  recent_activity?: StrategyRuntimeActivity;
  config?: Record<string, unknown>;
}

export interface StrategyDrilldownReport {
  generated_at?: string;
  strategies: StrategyDrilldownEntry[];
  regime_breakdown?: ValidationRegime[];
  monthly_returns?: ValidationMonthlyReturn[];
  ranking?: ExperimentRankingItem[];
}

export interface HealthSnapshot {
  status?: string;
  pending_orders?: number;
  approvals_paused?: boolean;
  emergency_stop_active?: boolean;
  broker_health?: BrokerHealthSnapshot;
  reconciliation?: ReconciliationSnapshot;
}

export interface OverviewSnapshot {
  broker?: {
    name?: string;
    simulated?: boolean;
    allow_live_orders?: boolean;
  };
  controls?: {
    approvals_paused?: boolean;
    emergency_stop_active?: boolean;
    last_action?: {
      action?: string;
      reason?: string;
      timestamp?: string;
    };
  };
  health?: {
    status?: string;
    pending_orders?: number;
    queue_total?: number;
    broker_health?: BrokerHealthSnapshot;
    reconciliation?: ReconciliationSnapshot;
  };
  outputs?: {
    analysis_timestamp?: string | null;
    validation_alpha_pct?: number | null;
  };
}

export interface BrokerConnectivityReport {
  broker: string;
  paper: boolean;
  configured: boolean;
  endpoint: string;
  credential_source?: string;
  status: string;
  available: boolean;
  message?: string;
  credentials?: Record<string, boolean>;
  account?: {
    portfolio_value?: number;
    cash?: number;
    buying_power?: number;
    currency?: string | null;
  };
  market_session?: Record<string, unknown>;
  asset_check?: Record<string, unknown>;
  broker_health?: BrokerHealthSnapshot;
}

export interface DashboardDataBundle {
  paperReport: PaperReport | null;
  liveReport: PaperReport | null;
  validationReport: ValidationReport | null;
  analysisResults: AnalysisResults | null;
  experimentReport: ExperimentReport | null;
  strategyDrilldown: StrategyDrilldownReport | null;
  pendingOrders: PendingOrder[];
  health: HealthSnapshot | null;
  overview: OverviewSnapshot | null;
  lastUpdated: string | null;
  loading: boolean;
  error: string | null;
}

declare global {
  interface Window {
    __HITL_AUTH_TOKEN__?: string;
  }
}

export function getOperatorAuthToken(): string {
  if (typeof window === 'undefined') {
    return '';
  }

  const params = new URLSearchParams(window.location.search);
  const queryToken = params.get('token')?.trim() ?? '';
  if (queryToken) {
    window.localStorage.setItem('hitlAuthToken', queryToken);
    return queryToken;
  }

  const storedToken = window.localStorage.getItem('hitlAuthToken')?.trim() ?? '';
  if (storedToken) {
    return storedToken;
  }

  return window.__HITL_AUTH_TOKEN__?.trim() ?? '';
}

export function setOperatorAuthToken(token: string): void {
  if (typeof window === 'undefined') {
    return;
  }
  const trimmed = token.trim();
  if (trimmed) {
    window.localStorage.setItem('hitlAuthToken', trimmed);
  } else {
    window.localStorage.removeItem('hitlAuthToken');
  }
}

export function clearOperatorAuthToken(): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.removeItem('hitlAuthToken');
}

export function buildAuthHeaders(headers: HeadersInit = {}): HeadersInit {
  const token = getOperatorAuthToken();
  if (!token) {
    return headers;
  }
  return {
    ...headers,
    Authorization: `Bearer ${token}`,
  };
}

export function buildAuthedUrl(url: string): string {
  const token = getOperatorAuthToken();
  if (!token || typeof window === 'undefined') {
    return url;
  }
  const resolved = new URL(url, window.location.origin);
  resolved.searchParams.set('token', token);
  return `${resolved.pathname}${resolved.search}${resolved.hash}`;
}

export async function fetchJson<T>(url: string): Promise<T | null> {
  const response = await fetch(url, {
    headers: buildAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function formatCurrency(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "₹--";
  }
  return `₹${value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function formatPercent(
  value: number | null | undefined,
  digits = 1,
  scale = 1,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  const rendered = (value * scale).toFixed(digits);
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${rendered}%`;
}

export function formatCompactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return Intl.NumberFormat(undefined, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function humanizeStrategyName(name: string): string {
  return name
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function inferAssetType(symbol: string): string {
  if (symbol.includes("BTC") || symbol.includes("ETH")) {
    return "CRYPTO";
  }
  if (symbol.includes("/") || symbol.endsWith("JPY")) {
    return "FOREX";
  }
  if (symbol.includes("!") || symbol.startsWith("ES") || symbol.startsWith("NQ")) {
    return "FUTURES";
  }
  return "EQUITY";
}

export function formatTimestampLabel(timestamp: string | undefined, dateOnly = false): string {
  if (!timestamp) {
    return "--";
  }
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return timestamp;
  }
  if (dateOnly) {
    return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function latestKnownPrice(
  symbol: string,
  analysis: AnalysisResults | null,
  paper: PaperReport | null,
  fallback: number,
): number {
  const skillPrice = analysis?.fundamentals_skill?.payload?.[symbol]?.insights?.currentPrice;
  if (typeof skillPrice === "number" && skillPrice > 0) {
    return skillPrice;
  }

  const recentTrade = paper?.recent_trades.find((trade) => trade.symbol === symbol);
  if (recentTrade?.execution_price && recentTrade.execution_price > 0) {
    return recentTrade.execution_price;
  }

  return fallback;
}
