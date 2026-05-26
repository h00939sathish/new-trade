import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  MinusCircle,
  RefreshCw,
  ShieldX,
  Signal,
  SignalZero,
  Wallet,
  PlugZap,
} from 'lucide-react';
import {
  buildAuthHeaders,
  type BrokerConnectivityReport,
  formatCurrency,
} from '../lib/dashboard-data';
import { cn } from '../lib/utils';

interface BrokerStatusProps {
  data?: DashboardDataBundle;
}

const BROKERS = [
  { id: 'simulated', label: 'Simulated', api: '/api/connectivity/simulated' },
  { id: 'alpaca', label: 'Alpaca', api: '/api/connectivity/alpaca' },
  { id: 'zerodha', label: 'Zerodha', api: '/api/connectivity/zerodha' },
  { id: 'angel_one', label: 'Angel One', api: '/api/connectivity/angel-one' },
  { id: 'groww', label: 'Groww', api: '/api/connectivity/groww' },
] as const;

interface BrokerReportState {
  report: BrokerConnectivityReport | null;
  loading: boolean;
  error: string | null;
}

function BrokerCard({
  broker,
}: {
  broker: (typeof BROKERS)[number];
}) {
  const [state, setState] = useState<BrokerReportState>({
    report: null,
    loading: true,
    error: null,
  });

  const refresh = async () => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const response = await fetch(broker.api, { headers: buildAuthHeaders() });
      if (!response.ok) {
        throw new Error(`${broker.label} check returned ${response.status}`);
      }
      const payload = await response.json();
      setState({ report: payload as BrokerConnectivityReport, loading: false, error: null });
    } catch (err) {
      setState({
        report: null,
        loading: false,
        error: err instanceof Error ? err.message : 'Connectivity check failed',
      });
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const { report, loading, error } = state;
  const isHealthy = report?.available === true;
  const isConfigured = report?.configured === true;
  const isMissing = !isConfigured && report?.status === 'missing_credentials';
  const statusLabel = loading
    ? 'CHECKING'
    : isHealthy
      ? 'CONNECTED'
      : isMissing
        ? 'MISSING CREDS'
        : 'FAILED';

  const statusClass = loading
    ? 'border-[var(--color-text-secondary)]/30'
    : isHealthy
      ? 'border-[var(--color-success)]/30'
      : isMissing
        ? 'border-[var(--color-warning)]/30'
        : 'border-[var(--color-danger)]/30';

  const statusIcon = loading ? (
    <RefreshCw size={18} className="animate-spin text-[var(--color-text-secondary)]" />
  ) : isHealthy ? (
    <CheckCircle2 size={18} className="text-[var(--color-success)]" />
  ) : isMissing ? (
    <MinusCircle size={18} className="text-[var(--color-warning)]" />
  ) : (
    <ShieldX size={18} className="text-[var(--color-danger)]" />
  );

  const brokerHealth = report?.broker_health;
  const consecutiveFailures = brokerHealth?.consecutive_failures ?? 0;
  const lastError = brokerHealth?.last_error ?? report?.message;
  const account = report?.account;

  const credentials = report?.credentials ?? {};
  const credCount = Object.values(credentials).filter(Boolean).length;
  const credTotal = Object.keys(credentials).length;

  const marketSession = report?.market_session as
    | { known?: boolean; is_open?: boolean; reason?: string }
    | undefined;
  const sessionStatus = marketSession?.known
    ? marketSession.is_open
      ? 'OPEN'
      : 'CLOSED'
    : 'UNKNOWN';

  return (
    <div
      className={cn(
        'panel p-5 border transition-all hover:border-[var(--color-accent)]/50',
        statusClass,
      )}
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex items-center gap-3">
          {statusIcon}
          <div>
            <h3 className="font-semibold text-sm">{broker.label}</h3>
            <p className="text-xs text-[var(--color-text-secondary)] font-mono">
              {report?.endpoint ?? '--'}
            </p>
          </div>
        </div>
        <span
          className={cn(
            'text-[10px] font-mono px-2 py-1 rounded border',
            loading
              ? 'bg-[var(--color-text-secondary)]/10 text-[var(--color-text-secondary)] border-[var(--color-text-secondary)]/20'
              : isHealthy
                ? 'bg-[var(--color-success)]/10 text-[var(--color-success)] border-[var(--color-success)]/20'
                : isMissing
                  ? 'bg-[var(--color-warning)]/10 text-[var(--color-warning)] border-[var(--color-warning)]/20'
                  : 'bg-[var(--color-danger)]/10 text-[var(--color-danger)] border-[var(--color-danger)]/20',
          )}
        >
          {statusLabel}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3">
          <div className="flex items-center gap-1.5 text-[var(--color-text-secondary)] text-[10px] uppercase">
            <Wallet size={12} />
            Portfolio
          </div>
          <div className="mt-1 text-sm font-medium">
            {formatCurrency(account?.portfolio_value ?? null)}
          </div>
        </div>
        <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3">
          <div className="flex items-center gap-1.5 text-[var(--color-text-secondary)] text-[10px] uppercase">
            <SignalZero size={12} />
            Cash
          </div>
          <div className="mt-1 text-sm font-medium">
            {formatCurrency(account?.cash ?? null)}
          </div>
        </div>
        <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3">
          <div className="flex items-center gap-1.5 text-[var(--color-text-secondary)] text-[10px] uppercase">
            <PlugZap size={12} />
            Credentials
          </div>
          <div className="mt-1 text-sm font-medium">
            {credTotal > 0 ? `${credCount}/${credTotal} set` : 'N/A'}
          </div>
        </div>
        <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3">
          <div className="flex items-center gap-1.5 text-[var(--color-text-secondary)] text-[10px] uppercase">
            <Clock size={12} />
            Session
          </div>
          <div className="mt-1 text-sm font-medium">
            {sessionStatus}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-4 text-xs font-mono">
        <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-2">
          <div className="text-[var(--color-text-secondary)]">Failures</div>
          <div
            className={cn(
              consecutiveFailures > 0
                ? 'text-[var(--color-danger)]'
                : 'text-[var(--color-success)]',
            )}
          >
            {consecutiveFailures}
          </div>
        </div>
        <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-2">
          <div className="text-[var(--color-text-secondary)]">Wrapped</div>
          <div className="truncate" title={brokerHealth?.wrapped_broker ?? '--'}>
            {brokerHealth?.wrapped_broker ?? '--'}
          </div>
        </div>
        <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-2">
          <div className="text-[var(--color-text-secondary)]">Source</div>
          <div>{(report?.credential_source ?? '--').toUpperCase()}</div>
        </div>
      </div>

      {lastError && (
        <div className="rounded border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 px-3 py-2 text-xs font-mono text-[var(--color-danger)] flex items-start gap-2 mb-4">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
          <span className="line-clamp-2">{lastError}</span>
        </div>
      )}

      <button
        onClick={() => void refresh()}
        disabled={loading}
        className="w-full bg-[var(--color-accent)]/10 text-[var(--color-accent)] hover:bg-[var(--color-accent)] hover:text-white text-sm font-bold px-4 py-2 rounded transition-colors flex items-center justify-center gap-2 disabled:opacity-60"
      >
        <RefreshCw size={16} className={cn(loading && 'animate-spin')} />
        Refresh {broker.label}
      </button>
    </div>
  );
}

export function BrokerStatus(_props: BrokerStatusProps) {
  return (
    <div className="flex flex-col gap-8 max-w-6xl mx-auto pb-10">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text-primary)]">
            Broker Status
          </h2>
          <p className="text-sm text-[var(--color-text-secondary)] font-mono mt-1">
            Real-time health metrics for all configured brokers
          </p>
        </div>
        <button
          onClick={handleRefresh}
          className="bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent)]/80 text-sm font-bold px-4 py-2 rounded transition-colors flex items-center gap-2"
        >
          <RefreshCw size={16} />
          Refresh All
        </button>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {BROKERS.map((broker) => (
          <BrokerCard key={broker.id} broker={broker} />
        ))}
      </div>

      <div className="panel p-5">
        <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
          <Signal size={16} className="text-[var(--color-accent)]" />
          Health Legend
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={14} className="text-[var(--color-success)]" />
            <span className="text-[var(--color-text-secondary)]">Connected</span>
          </div>
          <div className="flex items-center gap-2">
            <MinusCircle size={14} className="text-[var(--color-warning)]" />
            <span className="text-[var(--color-text-secondary)]">Missing Credentials</span>
          </div>
          <div className="flex items-center gap-2">
            <ShieldX size={14} className="text-[var(--color-danger)]" />
            <span className="text-[var(--color-text-secondary)]">Connection Failed</span>
          </div>
          <div className="flex items-center gap-2">
            <RefreshCw size={14} className="animate-spin text-[var(--color-text-secondary)]" />
            <span className="text-[var(--color-text-secondary)]">Checking...</span>
          </div>
        </div>
      </div>
    </div>
  );
}