import { ArrowDownRight, ArrowUpRight, Percent, TrendingUp, ShieldAlert, Activity } from 'lucide-react';
import { cn } from '../lib/utils';
import {
  type DashboardDataBundle,
  formatCompactNumber,
  formatCurrency,
  formatPercent,
} from '../lib/dashboard-data';

interface MetricsRowProps {
  data: DashboardDataBundle;
}

export function MetricsRow({ data }: MetricsRowProps) {
  const paper = data.paperReport?.summary;
  const validation = data.validationReport;
  const brokerHealth = data.health?.broker_health ?? data.overview?.health?.broker_health ?? data.paperReport?.broker_health;
  const reconciliation = data.health?.reconciliation ?? data.overview?.health?.reconciliation ?? data.paperReport?.reconciliation;
  const sharpe = validation?.summary?.sharpe_ratio ?? null;
  const maxDrawdown = validation?.summary?.max_drawdown ?? null;
  const drawdownLimit = validation?.configuration?.risk_management?.max_drawdown_pct ?? null;
  const alphaPct = validation?.benchmark_comparison?.alpha_pct ?? null;
  const dayPnl = paper?.day_pnl ?? null;
  const previousValue = paper ? paper.portfolio_value - paper.day_pnl : null;
  const dayReturnPct = previousValue && previousValue > 0 && dayPnl !== null ? (dayPnl / previousValue) * 100 : null;
  const activePositions = paper?.open_positions ?? null;
  const pendingOrders = data.pendingOrders.length;

  const metrics = [
    {
      label: 'Total Return',
      value: formatPercent(paper?.total_return_pct ?? validation?.benchmark_comparison?.strategy_total_return_pct ?? null),
      sub: alphaPct !== null ? `Alpha ${formatPercent(alphaPct, 1)}` : 'Awaiting validation',
      trend: (paper?.total_return_pct ?? 0) >= 0 ? 'up' : 'down',
      icon: TrendingUp,
    },
    {
      label: 'Daily Return',
      value: formatPercent(dayReturnPct),
      sub: dayPnl !== null ? formatCurrency(dayPnl) : 'No intraday PnL',
      trend: (dayReturnPct ?? 0) >= 0 ? 'up' : 'down',
      icon: Activity,
    },
    {
      label: 'Sharpe Ratio',
      value: sharpe !== null && sharpe !== undefined ? sharpe.toFixed(2) : '--',
      sub: validation?.configuration?.benchmark ? `vs ${validation.configuration.benchmark}` : 'Benchmark unavailable',
      trend: (sharpe ?? 0) >= 1 ? 'up' : 'neutral',
      icon: Percent,
    },
    {
      label: 'Max Drawdown',
      value: formatPercent(maxDrawdown, 1, 100),
      sub: drawdownLimit !== null ? `Limit: ${formatPercent(drawdownLimit, 0, 100)}` : 'Limit unavailable',
      trend: 'down',
      icon: ShieldAlert,
    },
    {
      label: 'Active Positions',
      value: activePositions !== null ? String(activePositions) : '--',
      sub: reconciliation?.matched === false
        ? `Reconciliation drift · ${Object.keys(reconciliation.share_deltas ?? {}).length} symbols`
        : brokerHealth?.available === false
        ? `Broker outage · ${brokerHealth.consecutive_failures ?? 0} failures`
        : pendingOrders > 0 ? `Pending: ${pendingOrders}` : `Trades: ${formatCompactNumber(paper?.total_trades ?? 0)}`,
      trend: reconciliation?.matched === false || brokerHealth?.available === false ? 'down' : 'neutral',
      icon: Activity,
    },
  ] as const;

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      {metrics.map((metric, index) => {
        const Icon = metric.icon;
        const isUp = metric.trend === 'up';
        const isDown = metric.trend === 'down';

        return (
          <div key={index} className="panel p-4 flex flex-col gap-2 relative overflow-hidden group hover:border-[var(--color-accent)]/50 transition-colors">
            <div className="flex justify-between items-start">
              <span className="text-xs font-mono text-[var(--color-text-secondary)]">{metric.label}</span>
              <Icon size={14} className="text-[var(--color-text-secondary)] opacity-50" />
            </div>

            <div className="flex items-end gap-2 mt-1">
              <span className={cn(
                'text-2xl font-bold tracking-tight',
                isUp ? 'text-[var(--color-success)]' : isDown ? 'text-[var(--color-danger)]' : 'text-white',
              )}>
                {metric.value}
              </span>
            </div>

            <div className="flex items-center gap-1 text-[10px] font-mono text-[var(--color-text-secondary)]">
              {isUp && <ArrowUpRight size={12} className="text-[var(--color-success)]" />}
              {isDown && <ArrowDownRight size={12} className="text-[var(--color-danger)]" />}
              {metric.sub}
            </div>

            <div className={cn(
              'absolute -bottom-4 -right-4 w-16 h-16 rounded-full blur-2xl opacity-10 group-hover:opacity-20 transition-opacity',
              isUp ? 'bg-[var(--color-success)]' : isDown ? 'bg-[var(--color-danger)]' : 'bg-[var(--color-accent)]',
            )} />
          </div>
        );
      })}
    </div>
  );
}
