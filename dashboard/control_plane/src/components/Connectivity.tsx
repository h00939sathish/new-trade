import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, KeyRound, RefreshCw, ServerCog, ShieldX } from 'lucide-react';
import {
  buildAuthHeaders,
  type BrokerConnectivityReport,
  type DashboardDataBundle,
  formatCurrency,
} from '../lib/dashboard-data';
import { cn } from '../lib/utils';

interface ConnectivityProps {
  data: DashboardDataBundle;
}

interface ConnectivityCardProps {
  report: BrokerConnectivityReport | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => Promise<void>;
  activeBrokerName: string;
}

function ConnectivityCard({ report, loading, error, onRefresh, activeBrokerName }: ConnectivityCardProps) {
  const isHealthy = report?.available === true;
  const statusLabel = loading ? 'CHECKING' : isHealthy ? 'CONNECTED' : 'FAILED';
  const brokerLabel = report?.broker === 'angel_one' ? 'Angel One SmartAPI' : 'Alpaca Paper API';
  const assetLabel = report?.broker === 'angel_one' ? 'Asset Check (`SBIN-EQ`)' : 'Asset Check (`AAPL`)';

  return (
    <div className="flex flex-col gap-6">
      <div className={cn(
        'panel p-5 border',
        isHealthy ? 'border-[var(--color-success)]/30' : 'border-[var(--color-danger)]/30',
      )}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              {isHealthy ? (
                <CheckCircle2 size={18} className="text-[var(--color-success)]" />
              ) : (
                <ShieldX size={18} className="text-[var(--color-danger)]" />
              )}
              <h3 className="font-semibold text-sm">{brokerLabel}</h3>
              <span className={cn(
                'text-[10px] font-mono px-2 py-1 rounded border',
                isHealthy
                  ? 'bg-[var(--color-success)]/10 text-[var(--color-success)] border-[var(--color-success)]/20'
                  : 'bg-[var(--color-danger)]/10 text-[var(--color-danger)] border-[var(--color-danger)]/20',
              )}>
                {statusLabel}
              </span>
            </div>
            <p className="text-sm text-[var(--color-text-secondary)] font-mono mt-2">
              {error ?? report?.message ?? 'Awaiting connectivity result'}
            </p>
          </div>
          <div className="text-xs font-mono text-[var(--color-text-secondary)] text-right">
            Endpoint
            <div className="text-white mt-1">{report?.endpoint ?? '--'}</div>
          </div>
        </div>
        <button
          onClick={() => void onRefresh()}
          disabled={loading}
          className="mt-4 bg-[var(--color-accent)]/10 text-[var(--color-accent)] hover:bg-[var(--color-accent)] hover:text-white text-sm font-bold px-4 py-2 rounded transition-colors flex items-center gap-2 disabled:opacity-60"
        >
          <RefreshCw size={16} className={cn(loading && 'animate-spin')} />
          Refresh Check
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="panel p-5 flex flex-col gap-4">
          <h3 className="font-semibold text-sm flex items-center gap-2">
            <KeyRound size={16} className="text-[var(--color-accent)]" />
            Credential State
          </h3>
          <div className="grid grid-cols-2 gap-3 text-xs font-mono">
            {Object.entries(report?.credentials ?? {}).map(([key, present]) => (
              <div key={key} className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3">
                <div className="text-[var(--color-text-secondary)]">{key.replaceAll('_', ' ').toUpperCase()}</div>
                <div className={cn(Boolean(present) ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]', 'mt-2')}>
                  {present ? 'PRESENT' : 'MISSING'}
                </div>
              </div>
            ))}
          </div>
          <div className="text-xs font-mono text-[var(--color-text-secondary)]">
            Credential source: {(report?.credential_source ?? 'unknown').toUpperCase()}
          </div>
          {!isHealthy && (
            <div className="rounded border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 px-3 py-2 text-xs font-mono text-[var(--color-text-secondary)] flex items-start gap-2">
              <AlertTriangle size={14} className="text-[var(--color-warning)] mt-0.5" />
              Auth must pass here before control-plane manual execution can reach the live broker successfully.
            </div>
          )}
        </div>

        <div className="panel p-5 flex flex-col gap-4">
          <h3 className="font-semibold text-sm flex items-center gap-2">
            <ServerCog size={16} className="text-[var(--color-accent)]" />
            Account Check
          </h3>
          <div className="grid grid-cols-3 gap-3 text-xs font-mono">
            <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3">
              <div className="text-[var(--color-text-secondary)]">PORTFOLIO</div>
              <div className="mt-2 text-white">{formatCurrency(report?.account?.portfolio_value ?? null)}</div>
            </div>
            <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3">
              <div className="text-[var(--color-text-secondary)]">CASH</div>
              <div className="mt-2 text-white">{formatCurrency(report?.account?.cash ?? null)}</div>
            </div>
            <div className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3">
              <div className="text-[var(--color-text-secondary)]">BUYING POWER</div>
              <div className="mt-2 text-white">{formatCurrency(report?.account?.buying_power ?? null)}</div>
            </div>
          </div>
          <div className="text-xs font-mono text-[var(--color-text-secondary)]">
            Active broker in runtime: {(activeBrokerName || report?.broker || 'simulated').toUpperCase()}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="panel p-5">
          <h3 className="font-semibold text-sm mb-3">Market Session</h3>
          <pre className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3 text-xs font-mono text-[var(--color-text-secondary)] overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(report?.market_session ?? {}, null, 2)}
          </pre>
        </div>
        <div className="panel p-5">
          <h3 className="font-semibold text-sm mb-3">{assetLabel}</h3>
          <pre className="bg-[var(--color-bg)] rounded border border-[var(--color-border)] p-3 text-xs font-mono text-[var(--color-text-secondary)] overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(report?.asset_check ?? {}, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}

export function Connectivity({ data }: ConnectivityProps) {
  const [alpacaReport, setAlpacaReport] = useState<BrokerConnectivityReport | null>(null);
  const [angelReport, setAngelReport] = useState<BrokerConnectivityReport | null>(null);
  const [loading, setLoading] = useState<{ alpaca: boolean; angel: boolean }>({ alpaca: true, angel: true });
  const [error, setError] = useState<{ alpaca: string | null; angel: string | null }>({ alpaca: null, angel: null });

  const refreshBroker = async (broker: 'alpaca' | 'angel') => {
    const endpoint = broker === 'alpaca' ? '/api/connectivity/alpaca' : '/api/connectivity/angel-one';
    const setter = broker === 'alpaca' ? setAlpacaReport : setAngelReport;
    setLoading((prev) => ({ ...prev, [broker]: true }));
    setError((prev) => ({ ...prev, [broker]: null }));
    try {
      const response = await fetch(endpoint, {
        headers: buildAuthHeaders(),
      });
      if (!response.ok) {
        throw new Error(`${endpoint} returned ${response.status}`);
      }
      const payload = await response.json() as BrokerConnectivityReport;
      setter(payload);
    } catch (err) {
      setError((prev) => ({
        ...prev,
        [broker]: err instanceof Error ? err.message : 'Connectivity check failed',
      }));
    } finally {
      setLoading((prev) => ({ ...prev, [broker]: false }));
    }
  };

  useEffect(() => {
    void refreshBroker('alpaca');
    void refreshBroker('angel');
  }, []);

  return (
    <div className="flex flex-col gap-8 max-w-6xl mx-auto pb-10">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text-primary)]">Broker Connectivity</h2>
          <p className="text-sm text-[var(--color-text-secondary)] font-mono mt-1">
            Real authentication and market session checks for U.S. and Indian broker adapters
          </p>
        </div>
      </header>

      <ConnectivityCard
        report={alpacaReport}
        loading={loading.alpaca}
        error={error.alpaca}
        onRefresh={() => refreshBroker('alpaca')}
        activeBrokerName={data.overview?.broker?.name ?? 'simulated'}
      />

      <ConnectivityCard
        report={angelReport}
        loading={loading.angel}
        error={error.angel}
        onRefresh={() => refreshBroker('angel')}
        activeBrokerName={data.overview?.broker?.name ?? 'simulated'}
      />
    </div>
  );
}
