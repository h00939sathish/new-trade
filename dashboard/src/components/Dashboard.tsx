import { type ComponentProps, useMemo, useState } from 'react';
import { ArrowDownRight, ArrowUpRight, BarChart3, ShieldAlert } from 'lucide-react';
import { cn } from '../lib/utils';
import { MetricsRow } from './MetricsRow';
import { EquityChart } from './EquityChart';
import { Layer1Signals } from './Layer1Signals';
import { Layer2LLM } from './Layer2LLM';
import { ActivePositions } from './ActivePositions';
import { PortfolioWeights } from './PortfolioWeights';
import {
  buildAuthHeaders,
  type DashboardDataBundle,
  formatCurrency,
  formatPercent,
} from '../lib/dashboard-data';

interface DashboardProps {
  data: DashboardDataBundle;
  onRefresh: () => Promise<void>;
}

export function Dashboard({ data, onRefresh }: DashboardProps) {
  const [actionPending, setActionPending] = useState(false);
  const [approvalPending, setApprovalPending] = useState(false);

  const portfolioValue = data.paperReport?.summary.portfolio_value ?? data.validationReport?.summary?.final_value ?? 0;
  const dayPnl = data.paperReport?.summary.day_pnl ?? 0;
  const baseValue = portfolioValue - dayPnl;
  const intradayReturnPct = baseValue > 0 ? (dayPnl / baseValue) * 100 : 0;
  const brokerHealth = data.health?.broker_health ?? data.overview?.health?.broker_health ?? data.paperReport?.broker_health;
  const reconciliation = data.health?.reconciliation ?? data.overview?.health?.reconciliation ?? data.paperReport?.reconciliation;
  const systemBadge = useMemo(() => {
    if (data.health?.emergency_stop_active) {
      return { label: 'SYSTEM: HALTED', className: 'bg-[var(--color-danger)]/10 text-[var(--color-danger)] border-[var(--color-danger)]/20' };
    }
    if (reconciliation && reconciliation.matched === false) {
      return { label: 'SYSTEM: RECONCILING', className: 'bg-[var(--color-warning)]/10 text-[var(--color-warning)] border-[var(--color-warning)]/20' };
    }
    if (brokerHealth && brokerHealth.available === false) {
      return { label: 'SYSTEM: DEGRADED', className: 'bg-[var(--color-warning)]/10 text-[var(--color-warning)] border-[var(--color-warning)]/20' };
    }
    if (data.overview?.broker?.allow_live_orders) {
      return { label: 'SYSTEM: LIVE', className: 'bg-[var(--color-success)]/10 text-[var(--color-success)] border-[var(--color-success)]/20' };
    }
    return { label: 'SYSTEM: PAPER', className: 'bg-[var(--color-warning)]/10 text-[var(--color-warning)] border-[var(--color-warning)]/20' };
  }, [brokerHealth, data.health, data.overview, reconciliation]);
  const approvalsPaused = Boolean(data.overview?.controls?.approvals_paused);

  const handleEmergencyAction = async () => {
    const isActive = Boolean(data.health?.emergency_stop_active);
    const url = isActive
      ? '/api/control-plane/controls/reset'
      : '/api/control-plane/controls/emergency-stop';

    setActionPending(true);
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          reason: isActive ? 'dashboard reset' : 'dashboard kill switch',
        }),
      });
      if (!response.ok) {
        throw new Error(`Control action failed with ${response.status}`);
      }
      await onRefresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Control action failed');
    } finally {
      setActionPending(false);
    }
  };

  const handleApprovalPause = async () => {
    setApprovalPending(true);
    try {
      const response = await fetch('/api/control-plane/controls/approvals', {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          paused: !approvalsPaused,
          reason: approvalsPaused ? 'dashboard resume approvals' : 'dashboard pause approvals',
        }),
      });
      if (!response.ok) {
        throw new Error(`Approval control failed with ${response.status}`);
      }
      await onRefresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Approval control failed');
    } finally {
      setApprovalPending(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 max-w-7xl mx-auto pb-10">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text-primary)]">Pro Alpha Terminal</h2>
          <div className="flex flex-wrap items-center gap-2 mt-2 text-[10px] font-mono text-[var(--color-text-secondary)]">
            <span className={cn('px-2 py-1 rounded border', systemBadge.className)}>{systemBadge.label}</span>
            <span className="bg-[var(--color-panel-hover)] px-2 py-1 rounded border border-[var(--color-border)]">
              BROKER: {(data.overview?.broker?.name ?? 'simulated').toUpperCase()}
            </span>
            <span className="bg-[var(--color-panel-hover)] px-2 py-1 rounded border border-[var(--color-border)]">
              UNIVERSE: {data.analysisResults?.market_data_symbols?.length ?? data.validationReport?.configuration?.symbols?.length ?? 0} SYMBOLS
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="panel px-4 py-2 flex items-center gap-3">
            <span className="text-xs font-mono text-[var(--color-text-secondary)]">PORTFOLIO</span>
            <span className="text-xl font-bold font-mono">{formatCurrency(portfolioValue)}</span>
            <span className={cn(
              'text-xs font-mono flex items-center',
              intradayReturnPct >= 0 ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]',
            )}>
              {intradayReturnPct >= 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
              {formatPercent(intradayReturnPct)}
            </span>
          </div>

          <button
            onClick={() => void handleApprovalPause()}
            disabled={approvalPending || actionPending}
            className={cn(
              'transition-colors px-4 py-2 rounded-md font-bold text-sm flex items-center gap-2 disabled:opacity-60 border',
              approvalsPaused
                ? 'bg-[var(--color-warning)]/10 text-[var(--color-warning)] border-[var(--color-warning)]/30 hover:bg-[var(--color-warning)] hover:text-black'
                : 'bg-[var(--color-panel-hover)] text-[var(--color-text-secondary)] border-[var(--color-border)] hover:text-white hover:border-[var(--color-accent)]/40',
            )}
          >
            {approvalsPaused ? 'RESUME APPROVALS' : 'PAUSE APPROVALS'}
          </button>
          <button
            onClick={() => void handleEmergencyAction()}
            disabled={actionPending}
            className={cn(
              'transition-colors px-4 py-2 rounded-md font-bold text-sm flex items-center gap-2 shadow-[0_0_15px_rgba(239,68,68,0.2)] disabled:opacity-60',
              data.health?.emergency_stop_active
                ? 'bg-[var(--color-success)]/10 text-[var(--color-success)] border border-[var(--color-success)]/30 hover:bg-[var(--color-success)] hover:text-white'
                : 'bg-[var(--color-danger)]/10 text-[var(--color-danger)] border border-[var(--color-danger)]/30 hover:bg-[var(--color-danger)] hover:text-white',
            )}
          >
            <ShieldAlert size={16} />
            {data.health?.emergency_stop_active ? 'RESET HALT' : 'KILL SWITCH'}
          </button>
        </div>
      </header>

      {brokerHealth?.available === false && (
        <div className="panel border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 px-4 py-3">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="text-sm font-bold text-[var(--color-danger)]">Broker outage detected</div>
              <div className="mt-1 text-xs font-mono text-[var(--color-text-secondary)]">
                {(brokerHealth.wrapped_broker ?? data.overview?.broker?.name ?? 'broker').toUpperCase()} unavailable
                {typeof brokerHealth.consecutive_failures === 'number' ? ` · failures: ${brokerHealth.consecutive_failures}` : ''}
                {brokerHealth.context ? ` · context: ${brokerHealth.context}` : ''}
              </div>
            </div>
            <div className="text-xs font-mono text-[var(--color-text-secondary)] md:text-right">
              {brokerHealth.last_error ? `LAST ERROR: ${brokerHealth.last_error}` : 'LAST ERROR: unavailable'}
            </div>
          </div>
        </div>
      )}

      {reconciliation?.matched === false && (
        <div className="panel border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 px-4 py-3">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="text-sm font-bold text-[var(--color-warning)]">Broker reconciliation mismatch</div>
              <div className="mt-1 text-xs font-mono text-[var(--color-text-secondary)]">
                {(reconciliation.broker ?? data.overview?.broker?.name ?? 'broker').toUpperCase()} differs from local portfolio state
                {typeof reconciliation.cash_delta === 'number' ? ` · cash Δ ${formatCurrency(reconciliation.cash_delta)}` : ''}
                {typeof reconciliation.portfolio_value_delta === 'number' ? ` · equity Δ ${formatCurrency(reconciliation.portfolio_value_delta)}` : ''}
              </div>
            </div>
            <div className="text-xs font-mono text-[var(--color-text-secondary)] md:text-right">
              {Object.keys(reconciliation.share_deltas ?? {}).length > 0
                ? `${Object.keys(reconciliation.share_deltas ?? {}).length} symbol mismatch${Object.keys(reconciliation.share_deltas ?? {}).length === 1 ? '' : 'es'}`
                : 'Quantity drift not detected'}
            </div>
          </div>
        </div>
      )}

      {approvalsPaused && (
        <div className="panel border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 px-4 py-3">
          <div className="flex flex-col gap-1">
            <div className="text-sm font-bold text-[var(--color-warning)]">Approvals paused</div>
            <div className="text-xs font-mono text-[var(--color-text-secondary)]">
              Pending orders stay queued until the operator resumes the approval workflow.
            </div>
          </div>
        </div>
      )}

      <MetricsRow data={data} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 flex flex-col gap-6">
          <div className="panel p-5 flex flex-col gap-4 h-[350px]">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-sm flex items-center gap-2">
                <LineChartIcon size={16} className="text-[var(--color-accent)]" />
                Equity Curve & Drawdown
              </h3>
              <div className="flex gap-2">
                {['1D', '1W', '1M', '3M', 'YTD'].map((tf, index) => (
                  <button key={tf} className={cn('text-xs font-mono px-2 py-1 rounded', index === 2 ? 'bg-[var(--color-border)] text-white' : 'text-[var(--color-text-secondary)] hover:text-white')}>
                    {tf}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex-1 min-h-0">
              <EquityChart paperReport={data.paperReport} validationReport={data.validationReport} />
            </div>
          </div>

          <Layer1Signals data={data} />
        </div>

        <div className="flex flex-col gap-6">
          <Layer2LLM data={data} />
          <PortfolioWeights data={data} />
          <ActivePositions data={data} onRefresh={onRefresh} />
        </div>
      </div>
    </div>
  );
}

function LineChartIcon(props: ComponentProps<typeof BarChart3>) {
  return <BarChart3 {...props} />;
}
