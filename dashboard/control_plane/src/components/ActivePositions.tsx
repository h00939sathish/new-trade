import { useMemo, useState } from 'react';
import { ArrowDownRight, ArrowUpRight, Briefcase, Clock, DollarSign, RefreshCw } from 'lucide-react';
import { cn } from '../lib/utils';
import {
  buildAuthHeaders,
  type DashboardDataBundle,
  formatCurrency,
  formatTimestampLabel,
  inferAssetType,
  latestKnownPrice,
} from '../lib/dashboard-data';

interface ActivePositionsProps {
  data: DashboardDataBundle;
  onRefresh: () => Promise<void>;
}

export function ActivePositions({ data, onRefresh }: ActivePositionsProps) {
  const [pendingActionId, setPendingActionId] = useState<number | null>(null);

  const positions = useMemo(() => {
    const realPositions = (data.paperReport?.positions ?? []).map((position) => {
      const entry = position.avg_cost > 0
        ? position.avg_cost
        : data.paperReport?.recent_trades.find((trade) => trade.symbol === position.symbol)?.execution_price ?? 0;
      const current = position.current_price > 0
        ? position.current_price
        : latestKnownPrice(position.symbol, data.analysisResults, data.paperReport, entry);
      const pnlValue = position.unrealized_pnl !== 0
        ? position.unrealized_pnl
        : (current - entry) * position.shares;
      const pnlPct = entry > 0 ? (current - entry) / entry : 0;

      return {
        id: `position-${position.symbol}`,
        symbol: position.symbol,
        asset: inferAssetType(position.symbol),
        broker: (data.overview?.broker?.name ?? 'simulated').toUpperCase(),
        type: position.shares >= 0 ? 'LONG' : 'SHORT',
        entry,
        current,
        pnlPct,
        pnlValue,
        status: 'ACTIVE',
        quantity: Math.abs(position.shares),
        createdAt: data.paperReport?.generated_at ?? data.lastUpdated ?? '',
      };
    });

    const queuedOrders = data.pendingOrders.map((order) => ({
      id: order.id,
      symbol: order.symbol,
      asset: inferAssetType(order.symbol),
      broker: (data.overview?.broker?.name ?? 'simulated').toUpperCase(),
      type: order.action === 'SELL' ? 'SHORT' : 'LONG',
      entry: order.price > 0 ? order.price : latestKnownPrice(order.symbol, data.analysisResults, data.paperReport, 0),
      current: latestKnownPrice(order.symbol, data.analysisResults, data.paperReport, order.price),
      pnlPct: 0,
      pnlValue: 0,
      status: 'PENDING_APPROVAL',
      quantity: order.quantity,
      createdAt: order.created_at ?? data.lastUpdated ?? '',
    }));

    return [...queuedOrders, ...realPositions].slice(0, 6);
  }, [data.analysisResults, data.lastUpdated, data.overview, data.paperReport, data.pendingOrders]);

  const handleApproval = async (orderId: number, action: 'approve' | 'reject') => {
    setPendingActionId(orderId);
    try {
      const response = await fetch(`/api/orders/${action}`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          order_id: orderId,
          action: action.toUpperCase(),
          notes: `dashboard_${action}`,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail ?? `${action} failed`);
      }
      await onRefresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : `${action} failed`);
    } finally {
      setPendingActionId(null);
    }
  };

  return (
    <div className="panel p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between border-b border-[var(--color-border)] pb-3">
        <h3 className="font-semibold text-sm flex items-center gap-2">
          <Briefcase size={16} className="text-[var(--color-accent)]" />
          Active Positions & Executions
        </h3>
        <button onClick={() => void onRefresh()} className="text-[var(--color-text-secondary)] hover:text-white transition-colors">
          <RefreshCw size={14} />
        </button>
      </div>

      <div className="flex flex-col gap-3">
        {positions.map((position) => {
          const isPositive = position.pnlPct >= 0;
          const isPending = position.status === 'PENDING_APPROVAL';

          return (
            <div key={position.id} className={cn(
              'bg-[var(--color-bg)] p-3 rounded border flex flex-col gap-2 transition-colors',
              isPending ? 'border-[var(--color-warning)]/50 bg-[var(--color-warning)]/5' : 'border-[var(--color-border)] hover:border-[var(--color-accent)]/30',
            )}>
              <div className="flex items-center justify-between">
                <div className="flex flex-col">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm">{position.symbol}</span>
                    <span className={cn(
                      'text-[9px] font-bold px-1.5 py-0.5 rounded',
                      position.type === 'LONG' ? 'bg-[var(--color-success)]/20 text-[var(--color-success)]' : 'bg-[var(--color-danger)]/20 text-[var(--color-danger)]',
                    )}>
                      {position.type}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="text-[8px] font-mono bg-[var(--color-border)] text-[var(--color-text-secondary)] px-1 py-0.5 rounded">{position.asset}</span>
                    <span className="text-[8px] font-mono text-[var(--color-text-secondary)]">{position.broker}</span>
                    <span className="text-[8px] font-mono text-[var(--color-text-secondary)]">QTY {position.quantity}</span>
                  </div>
                </div>
                {isPending ? (
                  <span className="text-[9px] font-mono bg-[var(--color-warning)]/20 text-[var(--color-warning)] px-1.5 py-0.5 rounded animate-pulse">
                    HUMAN APPROVAL REQ
                  </span>
                ) : (
                  <div className="flex items-center gap-1 text-xs font-mono">
                    <span className={isPositive ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}>
                      {isPositive ? '+' : ''}{(position.pnlPct * 100).toFixed(1)}%
                    </span>
                    {isPositive ? <ArrowUpRight size={12} className="text-[var(--color-success)]" /> : <ArrowDownRight size={12} className="text-[var(--color-danger)]" />}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-3 gap-2 text-[10px] font-mono text-[var(--color-text-secondary)]">
                <div className="flex flex-col">
                  <span>ENTRY</span>
                  <span className="text-white">{formatCurrency(position.entry)}</span>
                </div>
                <div className="flex flex-col">
                  <span>CURRENT</span>
                  <span className="text-white">{formatCurrency(position.current)}</span>
                </div>
                <div className="flex flex-col items-end">
                  <span>PNL</span>
                  <span className={isPositive ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}>
                    {position.pnlValue >= 0 ? '+' : ''}{formatCurrency(position.pnlValue).replace('₹', '₹')}
                  </span>
                </div>
              </div>

              {isPending && typeof position.id === 'number' && (
                <div className="flex gap-2 mt-2 pt-2 border-t border-[var(--color-border)]">
                  <button
                    disabled={pendingActionId === position.id}
                    onClick={() => void handleApproval(position.id, 'approve')}
                    className="flex-1 bg-[var(--color-success)]/20 text-[var(--color-success)] hover:bg-[var(--color-success)] hover:text-white text-[10px] font-bold py-1.5 rounded transition-colors disabled:opacity-50"
                  >
                    APPROVE
                  </button>
                  <button
                    disabled={pendingActionId === position.id}
                    onClick={() => void handleApproval(position.id, 'reject')}
                    className="flex-1 bg-[var(--color-danger)]/20 text-[var(--color-danger)] hover:bg-[var(--color-danger)] hover:text-white text-[10px] font-bold py-1.5 rounded transition-colors disabled:opacity-50"
                  >
                    REJECT
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-auto pt-3 border-t border-[var(--color-border)] flex items-center justify-between text-[10px] font-mono text-[var(--color-text-secondary)]">
        <span className="flex items-center gap-1"><Clock size={12} /> Last sync: {formatTimestampLabel(data.lastUpdated ?? data.paperReport?.generated_at)}</span>
        <span className="flex items-center gap-1"><DollarSign size={12} /> Broker: {(data.overview?.broker?.name ?? 'simulated').toUpperCase()}</span>
      </div>
    </div>
  );
}
