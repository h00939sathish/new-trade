import { useEffect, useMemo, useState } from 'react';
import { ArrowDownRight, ArrowUpRight, Server, Zap } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { cn } from '../lib/utils';
import {
  buildAuthHeaders,
  buildAuthedUrl,
  formatCurrency,
  formatTimestampLabel,
  type DashboardDataBundle,
  type PaperReport,
} from '../lib/dashboard-data';
import { useChartData, useIndicators, useSymbols } from '../lib/hooks';

interface LiveTradingProps {
  data: DashboardDataBundle;
  onRefresh: () => Promise<void>;
  mode: 'paper' | 'live';
}

export function LiveTrading({ data, onRefresh, mode }: LiveTradingProps) {
  const { symbols } = useSymbols();
  const report: PaperReport | null = mode === 'live' ? data.liveReport : data.paperReport;
  const modeLabel = mode === 'live' ? 'Live Money Trade' : 'Live Paper Trade';
  const configuredBroker = data.overview?.broker?.name;
  const defaultBroker = mode === 'live' && configuredBroker && configuredBroker !== 'simulated'
    ? configuredBroker
    : mode === 'live'
      ? 'angel_one'
      : 'simulated';
  const [quoteData, setQuoteData] = useState<{
    symbol: string;
    price: number;
    change: number;
    changePct: number;
    vol: number;
    trend: 'up' | 'down' | 'flat';
  }>({
    symbol: 'AAPL',
    price: 0,
    change: 0,
    changePct: 0,
    vol: 0,
    trend: 'flat',
  });
  const [wsStatus, setWsStatus] = useState<'CONNECTING' | 'CONNECTED' | 'DISCONNECTED'>('CONNECTING');
  const [selectedBroker, setSelectedBroker] = useState(defaultBroker);
  const [manualSymbol, setManualSymbol] = useState('AAPL');
  const [manualQuantity, setManualQuantity] = useState('1');
  const [tradePending, setTradePending] = useState(false);
  const [tradeMessage, setTradeMessage] = useState<string | null>(null);
  const { data: chartData, loading: chartLoading, error: chartError } = useChartData(manualSymbol, '1d', '3mo');
  const indicators = useIndicators(manualSymbol, '1d', '3mo');

  useEffect(() => {
    setSelectedBroker(defaultBroker);
  }, [defaultBroker]);

  useEffect(() => {
    if (symbols.length === 0) {
      return;
    }
    if (!manualSymbol || !symbols.includes(manualSymbol)) {
      setManualSymbol(symbols[0]);
    }
  }, [manualSymbol, symbols]);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsPath = buildAuthedUrl(`/ws/marketdata?broker=${encodeURIComponent(selectedBroker)}&symbol=${encodeURIComponent(manualSymbol)}`);
    const wsUrl = `${protocol}//${window.location.host}${wsPath}`;

    let ws: WebSocket;

    const connect = () => {
      setWsStatus('CONNECTING');
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setWsStatus('CONNECTED');
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'quote') {
            setQuoteData((prev) => {
              const newPrice = Number(payload.price ?? 0);
              return {
                symbol: String(payload.symbol ?? manualSymbol),
                price: newPrice,
                change: Number(payload.change ?? 0),
                changePct: Number(payload.change_pct ?? 0),
                vol: Number(payload.volume ?? 0),
                trend: newPrice > prev.price ? 'up' : newPrice < prev.price ? 'down' : prev.trend,
              };
            });
          }
        } catch (err) {
          console.error('Error parsing WS data:', err);
        }
      };

      ws.onclose = () => {
        setWsStatus('DISCONNECTED');
        setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      if (ws) {
        ws.close();
      }
    };
  }, [manualSymbol, selectedBroker]);

  const handleTrade = async (side: 'BUY' | 'SELL') => {
    try {
      setTradePending(true);
      setTradeMessage(null);
      const res = await fetch('/api/trade/execute', {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          broker: selectedBroker,
          symbol: manualSymbol,
          side,
          quantity: Number(manualQuantity),
        }),
      });
      const payload = await res.json();
      if (res.ok) {
        setTradeMessage(payload.message ?? `Queued ${side} ${manualQuantity} ${manualSymbol} via ${String(selectedBroker).toUpperCase()}`);
        await onRefresh();
      } else {
        setTradeMessage(`Order failed: ${payload.detail ?? payload.error ?? 'Unknown error'}`);
      }
    } catch (err) {
      console.error(err);
      setTradeMessage('Error executing trade');
    } finally {
      setTradePending(false);
    }
  };

  const chartSeries = useMemo(() => (
    (chartData ?? []).map((point) => ({
      time: new Date(point.time).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
      close: point.close,
      volume: point.volume,
    }))
  ), [chartData]);

  const latestIndicatorState = useMemo(() => {
    const rsi = indicators.rsi?.at(-1);
    const macd = indicators.macd?.macd?.at(-1);
    const signal = indicators.macd?.signal?.at(-1);
    const upper = indicators.bollinger?.upper?.at(-1);
    const middle = indicators.bollinger?.middle?.at(-1);
    const lower = indicators.bollinger?.lower?.at(-1);
    return { rsi, macd, signal, upper, middle, lower };
  }, [indicators]);

  return (
    <div className="flex flex-col gap-6 max-w-7xl mx-auto pb-10">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text-primary)]">Live Market Data & Execution</h2>
          <p className="text-sm text-[var(--color-text-secondary)] font-mono mt-1">
            {modeLabel} · holdings, order history, trade history, and broker quote snapshots
          </p>
        </div>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          ['PORTFOLIO', formatCurrency(report?.summary.portfolio_value)],
          ['CASH', formatCurrency(report?.summary.cash)],
          ['HOLDINGS', formatCurrency(report?.summary.holdings_value)],
          ['OPEN POSITIONS', String(report?.summary.open_positions ?? 0)],
        ].map(([label, value]) => (
          <div key={label} className="panel p-4">
            <div className="text-[10px] font-mono text-[var(--color-text-secondary)]">{label}</div>
            <div className="mt-2 text-lg font-bold text-white">{value}</div>
          </div>
        ))}
      </div>

      <div className="panel p-5 flex flex-col gap-4 border-[var(--color-accent)]/30">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm flex items-center gap-2">
            <Zap size={16} className="text-[var(--color-accent)]" />
            Manual Broker Execution
          </h3>
          <span className="text-[10px] font-mono bg-[var(--color-panel-hover)] px-2 py-1 rounded border border-[var(--color-border)]">
            ACTIVE BROKER: {selectedBroker.toUpperCase()}
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <label className="flex flex-col gap-1 text-xs font-mono text-[var(--color-text-secondary)]">
            BROKER
            <select value={selectedBroker} onChange={(e) => setSelectedBroker(e.target.value)} className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-3 py-2 text-sm text-white">
              {mode === 'paper' ? (
                <>
                  <option value="simulated">SIMULATED</option>
                  <option value="alpaca">ALPACA PAPER</option>
                </>
              ) : (
                <>
                  <option value="angel_one">ANGEL ONE</option>
                  <option value="groww">GROWW</option>
                  <option value="zerodha">ZERODHA</option>
                </>
              )}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-mono text-[var(--color-text-secondary)]">
            SYMBOL
            {symbols.length > 0 ? (
              <select
                value={manualSymbol}
                onChange={(e) => setManualSymbol(e.target.value)}
                className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-3 py-2 text-sm text-white font-mono"
              >
                {symbols.map((symbol) => (
                  <option key={symbol} value={symbol}>{symbol}</option>
                ))}
              </select>
            ) : (
              <input value={manualSymbol} onChange={(e) => setManualSymbol(e.target.value.toUpperCase())} className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-3 py-2 text-sm text-white font-mono" />
            )}
          </label>
          <label className="flex flex-col gap-1 text-xs font-mono text-[var(--color-text-secondary)]">
            QUANTITY
            <input value={manualQuantity} onChange={(e) => setManualQuantity(e.target.value)} className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-3 py-2 text-sm text-white font-mono" />
          </label>
          <div className="flex items-end gap-2">
            <button disabled={tradePending} onClick={() => void handleTrade('SELL')} className="flex-1 bg-[var(--color-danger)]/10 hover:bg-[var(--color-danger)] text-[var(--color-danger)] hover:text-white border border-[var(--color-danger)]/30 px-3 py-2 rounded text-[10px] font-bold transition-colors disabled:opacity-60">
              SELL
            </button>
            <button disabled={tradePending} onClick={() => void handleTrade('BUY')} className="flex-1 bg-[var(--color-success)]/10 hover:bg-[var(--color-success)] text-[var(--color-success)] hover:text-white border border-[var(--color-success)]/30 px-3 py-2 rounded text-[10px] font-bold transition-colors disabled:opacity-60">
              BUY
            </button>
          </div>
        </div>
        {tradeMessage && (
          <div className="text-xs font-mono text-[var(--color-text-secondary)] border-t border-[var(--color-border)] pt-3">
            {tradeMessage}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.8fr)_minmax(320px,0.9fr)] gap-6">
        <div className="panel p-5 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-sm flex items-center gap-2">
              <Server size={16} className="text-[var(--color-accent)]" />
              Market Data Explorer
            </h3>
            <span className="text-[10px] font-mono bg-[var(--color-panel-hover)] px-2 py-1 rounded border border-[var(--color-border)]">
              {manualSymbol}
            </span>
          </div>
          <div className="h-[320px]">
            {chartLoading ? (
              <div className="flex h-full items-center justify-center text-xs font-mono text-[var(--color-text-secondary)]">
                Loading market history...
              </div>
            ) : chartError ? (
              <div className="flex h-full items-center justify-center text-xs font-mono text-[var(--color-danger)]">
                {chartError}
              </div>
            ) : chartSeries.length === 0 ? (
              <div className="flex h-full items-center justify-center text-xs font-mono text-[var(--color-text-secondary)]">
                No market data available
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartSeries} margin={{ top: 10, right: 8, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="liveChartFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--color-accent)" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="var(--color-accent)" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.35} />
                  <XAxis dataKey="time" tick={{ fill: 'var(--color-text-secondary)', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: 'var(--color-text-secondary)', fontSize: 10 }} axisLine={false} tickLine={false} domain={['auto', 'auto']} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--color-panel)',
                      borderColor: 'var(--color-border)',
                      borderRadius: '8px',
                      fontFamily: 'var(--font-mono)',
                    }}
                  />
                  <Area type="monotone" dataKey="close" stroke="var(--color-accent)" strokeWidth={2} fill="url(#liveChartFill)" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="panel p-5 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-sm text-[var(--color-text-primary)]">Technical Snapshot</h3>
            <span className="text-[10px] font-mono text-[var(--color-text-secondary)]">1D · 3MO</span>
          </div>
          <div className="grid grid-cols-2 gap-3 text-xs font-mono">
            <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3">
              <div className="text-[var(--color-text-secondary)]">RSI</div>
              <div className={cn(
                'mt-2 text-lg font-bold',
                (latestIndicatorState.rsi ?? 50) > 70
                  ? 'text-[var(--color-danger)]'
                  : (latestIndicatorState.rsi ?? 50) < 30
                    ? 'text-[var(--color-success)]'
                    : 'text-white',
              )}>
                {latestIndicatorState.rsi?.toFixed(1) ?? '--'}
              </div>
            </div>
            <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3">
              <div className="text-[var(--color-text-secondary)]">MACD</div>
              <div className={cn(
                'mt-2 text-lg font-bold',
                (latestIndicatorState.macd ?? 0) >= (latestIndicatorState.signal ?? 0)
                  ? 'text-[var(--color-success)]'
                  : 'text-[var(--color-danger)]',
              )}>
                {latestIndicatorState.macd?.toFixed(2) ?? '--'}
              </div>
              <div className="mt-1 text-[10px] text-[var(--color-text-secondary)]">
                Signal {latestIndicatorState.signal?.toFixed(2) ?? '--'}
              </div>
            </div>
            <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3 col-span-2">
              <div className="text-[var(--color-text-secondary)]">Bollinger Bands</div>
              <div className="mt-2 flex items-center gap-2 text-sm font-bold">
                <span className="text-[var(--color-success)]">{latestIndicatorState.upper?.toFixed(2) ?? '--'}</span>
                <span className="text-[var(--color-text-secondary)]">/</span>
                <span className="text-white">{latestIndicatorState.middle?.toFixed(2) ?? '--'}</span>
                <span className="text-[var(--color-text-secondary)]">/</span>
                <span className="text-[var(--color-danger)]">{latestIndicatorState.lower?.toFixed(2) ?? '--'}</span>
              </div>
            </div>
            <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3 col-span-2">
              <div className="text-[var(--color-text-secondary)]">Latest Close</div>
              <div className="mt-2 text-lg font-bold text-white">
                {quoteData.price > 0
                  ? `$${quoteData.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                  : chartSeries.length > 0
                    ? `$${chartSeries[chartSeries.length - 1].close.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                    : '--'}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <ReportTable
          title="Holdings"
          empty="No holdings for this trading mode"
          headers={['SYMBOL', 'QTY', 'AVG', 'LTP', 'VALUE', 'P&L']}
          rows={(report?.positions ?? []).map((position) => [
            position.symbol,
            position.shares.toLocaleString(undefined, { maximumFractionDigits: 4 }),
            formatCurrency(position.avg_cost),
            formatCurrency(position.current_price),
            formatCurrency(position.market_value),
            formatCurrency(position.unrealized_pnl),
          ])}
        />
        <ReportTable
          title="Order History"
          empty="No recorded orders for this trading mode"
          headers={['TIME', 'SYMBOL', 'SIDE', 'QTY', 'STATUS']}
          rows={(report?.orders.recent ?? []).map((order) => [
            formatTimestampLabel(order.created_at ?? undefined),
            order.symbol,
            order.side,
            order.quantity.toLocaleString(undefined, { maximumFractionDigits: 4 }),
            order.status.toUpperCase(),
          ])}
        />
      </div>

      <ReportTable
        title="Trade History"
        empty="No trade history for this trading mode"
        headers={['TIME', 'SYMBOL', 'ACTION', 'QTY', 'PRICE', 'P&L', 'STRATEGY']}
        rows={(report?.recent_trades ?? []).map((trade) => [
          formatTimestampLabel(trade.timestamp),
          trade.symbol,
          trade.action,
          trade.shares.toLocaleString(undefined, { maximumFractionDigits: 4 }),
          formatCurrency(trade.execution_price || trade.price),
          formatCurrency(trade.pnl),
          trade.strategy ?? '--',
        ])}
      />

      <div className="panel flex flex-col overflow-hidden border-[var(--color-accent)]/30">
        <div className="p-5 border-b border-[var(--color-border)] flex items-center justify-between bg-[var(--color-panel-hover)]/50">
          <h3 className="font-semibold text-sm flex items-center gap-2">
            <Server size={16} className="text-[var(--color-accent)]" />
            Broker Quote Snapshot
          </h3>
          <div className="flex items-center gap-2 text-[10px] font-mono">
            <span className="flex items-center gap-1 text-[var(--color-text-secondary)]">
              <Server size={12} /> {selectedBroker.toUpperCase()}
            </span>
            <span className={cn(
              'px-2 py-1 rounded ml-2',
              wsStatus === 'CONNECTED' ? 'bg-[var(--color-success)]/20 text-[var(--color-success)]' :
              wsStatus === 'CONNECTING' ? 'bg-[var(--color-accent)]/20 text-[var(--color-accent)]' :
              'bg-[var(--color-danger)]/20 text-[var(--color-danger)]',
            )}>
              {wsStatus === 'CONNECTED' ? 'ACTIVE' : wsStatus}
            </span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-secondary)] bg-[var(--color-bg)]/50">
                <th className="p-4 font-medium">SYMBOL</th>
                <th className="p-4 font-medium">BROKER</th>
                <th className="p-4 font-medium text-right">LAST PRICE</th>
                <th className="p-4 font-medium text-right">CHANGE</th>
                <th className="p-4 font-medium text-right">VOLUME</th>
                <th className="p-4 font-medium text-center">EXECUTION</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              <tr className="border-b border-[var(--color-border)]/50 hover:bg-[var(--color-panel-hover)] transition-colors group">
                <td className="p-4 font-bold font-mono text-[var(--color-text-primary)]">{quoteData.symbol}</td>
                <td className="p-4 font-mono text-xs text-[var(--color-text-secondary)]">{selectedBroker.toUpperCase()}</td>
                <td className={cn(
                  'p-4 text-right font-mono font-bold transition-colors duration-300',
                  quoteData.trend === 'up' ? 'text-[var(--color-success)]' :
                  quoteData.trend === 'down' ? 'text-[var(--color-danger)]' :
                  'text-[var(--color-text-primary)]',
                )}>
                  ${quoteData.price > 0 ? quoteData.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '---'}
                </td>
                <td className="p-4 text-right">
                  <div className={cn(
                    'flex items-center justify-end gap-1 font-mono text-xs',
                    quoteData.change >= 0 ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]',
                  )}>
                    {quoteData.change >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                    <span>{quoteData.change > 0 ? '+' : ''}{quoteData.change.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                    <span className="opacity-70">({quoteData.changePct > 0 ? '+' : ''}{quoteData.changePct.toFixed(2)}%)</span>
                  </div>
                </td>
                <td className="p-4 text-right font-mono text-xs text-[var(--color-text-secondary)]">
                  {quoteData.vol > 0 ? quoteData.vol.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '---'}
                </td>
                <td className="p-4">
                  <div className="flex items-center justify-center gap-2">
                    <button onClick={() => void handleTrade('SELL')} disabled={tradePending} className="flex items-center gap-1 bg-[var(--color-danger)]/10 hover:bg-[var(--color-danger)] text-[var(--color-danger)] hover:text-white border border-[var(--color-danger)]/30 px-3 py-1.5 rounded text-[10px] font-bold transition-colors disabled:opacity-60">
                      SELL
                    </button>
                    <button onClick={() => void handleTrade('BUY')} disabled={tradePending} className="flex items-center gap-1 bg-[var(--color-success)]/10 hover:bg-[var(--color-success)] text-[var(--color-success)] hover:text-white border border-[var(--color-success)]/30 px-3 py-1.5 rounded text-[10px] font-bold transition-colors disabled:opacity-60">
                      BUY
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel p-5 border border-[var(--color-border)] flex flex-col gap-2">
        <h3 className="font-semibold text-sm text-[var(--color-text-primary)]">Data Source</h3>
        <p className="text-xs font-mono text-[var(--color-text-secondary)] leading-relaxed">
          {mode === 'live'
            ? 'Live-money history is read from source=live trade outcomes and broker-linked orders.'
            : 'Paper history is read from source=paper trade outcomes, with legacy local positions as a fallback.'}
        </p>
      </div>
    </div>
  );
}

interface ReportTableProps {
  title: string;
  empty: string;
  headers: string[];
  rows: string[][];
}

function ReportTable({ title, empty, headers, rows }: ReportTableProps) {
  return (
    <div className="panel flex flex-col overflow-hidden">
      <div className="p-4 border-b border-[var(--color-border)] bg-[var(--color-panel-hover)]/50">
        <h3 className="font-semibold text-sm text-[var(--color-text-primary)]">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-secondary)] bg-[var(--color-bg)]/50">
              {headers.map((header, index) => (
                <th key={header} className={cn('p-3 font-medium', index > 0 ? 'text-right' : '')}>{header}</th>
              ))}
            </tr>
          </thead>
          <tbody className="text-xs font-mono">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={headers.length} className="p-5 text-center text-[var(--color-text-secondary)]">{empty}</td>
              </tr>
            ) : rows.map((row, rowIndex) => (
              <tr key={`${title}-${rowIndex}`} className="border-b border-[var(--color-border)]/50 hover:bg-[var(--color-panel-hover)]">
                {row.map((value, index) => (
                  <td key={`${title}-${rowIndex}-${index}`} className={cn('p-3 text-[var(--color-text-primary)]', index > 0 ? 'text-right' : 'font-bold')}>
                    {value}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
