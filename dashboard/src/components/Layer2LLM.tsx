import { useMemo, useState } from 'react';
import { BrainCircuit, CheckCircle2, MessageSquare, Scale, ShieldAlert } from 'lucide-react';
import { cn } from '../lib/utils';
import {
  buildAuthHeaders,
  type DashboardDataBundle,
  formatPercent,
  humanizeStrategyName,
} from '../lib/dashboard-data';

interface Layer2LLMProps {
  data: DashboardDataBundle;
}

export function Layer2LLM({ data }: Layer2LLMProps) {
  const [submitting, setSubmitting] = useState(false);

  const summary = useMemo(() => {
    const sentiments = Object.entries(data.analysisResults?.sentiment ?? {});
    const topSentiment = [...sentiments].sort((left, right) => right[1].score - left[1].score)[0];
    const averageSentiment = sentiments.length > 0
      ? sentiments.reduce((sum, [, row]) => sum + row.score, 0) / sentiments.length
      : 0;
    const bestStrategy = [...(data.validationReport?.strategy_participation ?? [])]
      .sort((left, right) => (right.avg_confidence ?? 0) - (left.avg_confidence ?? 0))[0];
    const confidence = Math.min(95, Math.max(25, ((averageSentiment + 0.5) * 65) + ((bestStrategy?.avg_confidence ?? 0.5) * 25)));
    const decision = averageSentiment > 0.12 ? 'BUY' : averageSentiment < -0.08 ? 'SELL' : 'HOLD';

    return {
      topSymbol: topSentiment?.[0] ?? 'AAPL',
      topSentimentScore: topSentiment?.[1].score ?? 0,
      averageSentiment,
      bestStrategy: bestStrategy?.strategy ? humanizeStrategyName(bestStrategy.strategy) : 'Momentum',
      confidence,
      decision,
    };
  }, [data.analysisResults, data.validationReport]);

  const agents = [
    {
      id: 'analyzer',
      name: 'Analyzer Agent',
      icon: BrainCircuit,
      status: 'complete',
      output: `${summary.topSymbol} leads sentiment at ${summary.topSentimentScore.toFixed(2)}. ${data.analysisResults?.market_data_symbols?.length ?? 0} symbols processed from the latest artifact snapshot.`,
      color: 'text-[var(--color-accent)]',
    },
    {
      id: 'debate',
      name: 'Debate (Bull vs Bear)',
      icon: MessageSquare,
      status: 'complete',
      output: `${summary.bestStrategy} has the strongest confidence. Benchmark alpha is ${formatPercent(data.validationReport?.benchmark_comparison?.alpha_pct)} so the bullish case still needs proof out of sample.`,
      color: 'text-[var(--color-warning)]',
    },
    {
      id: 'risk',
      name: 'Risk Review',
      icon: ShieldAlert,
      status: 'complete',
      output: data.health?.emergency_stop_active
        ? 'Emergency stop is active. New approvals are blocked until the operator resets the system.'
        : `${data.pendingOrders.length} orders waiting for approval. Max drawdown remains ${formatPercent(data.validationReport?.summary?.max_drawdown, 1, 100)} in the latest validation run.`,
      color: 'text-[var(--color-danger)]',
    },
    {
      id: 'decision',
      name: 'Final Decision',
      icon: Scale,
      status: data.health?.emergency_stop_active ? 'paused' : 'active',
      output: data.health?.emergency_stop_active
        ? 'Execution paused by control plane halt.'
        : `Synthesizing sentiment, validation, and order queue state around ${summary.topSymbol}.`,
      color: 'text-[var(--color-success)]',
    },
  ] as const;

  const handleExecute = async () => {
    setSubmitting(true);
    try {
      const response = await fetch('/api/trade/execute', {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          broker: data.overview?.broker?.name ?? 'simulated',
          symbol: summary.topSymbol,
          side: summary.decision === 'SELL' ? 'SELL' : 'BUY',
          quantity: 1,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail ?? payload.error ?? 'Execution failed');
      }
      window.alert(payload.message ?? `Queued ${summary.decision} order for ${summary.topSymbol}`);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Execution failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="panel p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between border-b border-[var(--color-border)] pb-3">
        <h3 className="font-semibold text-sm flex items-center gap-2">
          <BrainCircuit size={16} className="text-[var(--color-accent)]" />
          Layer 2: Artifact Synthesis
        </h3>
        <span className="text-[10px] font-mono text-[var(--color-text-secondary)] border border-[var(--color-border)] px-2 py-1 rounded">
          SOURCE: SAVED ANALYSIS + VALIDATION ARTIFACTS
        </span>
      </div>

      <div className="flex flex-col gap-4 mt-2">
        {agents.map((agent, index) => {
          const Icon = agent.icon;
          const isComplete = agent.status === 'complete';
          const isActive = agent.status === 'active';

          return (
            <div key={agent.id} className="relative flex gap-4">
              {index < agents.length - 1 && (
                <div className="absolute left-[15px] top-[30px] bottom-[-20px] w-[2px] bg-[var(--color-border)]"></div>
              )}

              <div className={cn(
                'w-8 h-8 rounded-full flex items-center justify-center z-10 border-2 bg-[var(--color-bg)]',
                isComplete ? 'border-[var(--color-success)] text-[var(--color-success)]' :
                isActive ? 'border-[var(--color-accent)] text-[var(--color-accent)] shadow-[0_0_10px_rgba(59,130,246,0.5)]' :
                'border-[var(--color-border)] text-[var(--color-text-secondary)]',
              )}>
                {isComplete ? <CheckCircle2 size={14} /> : <Icon size={14} />}
              </div>

              <div className={cn(
                'flex-1 bg-[var(--color-bg)] p-3 rounded border border-[var(--color-border)]',
                isActive && 'border-[var(--color-accent)]/50',
              )}>
                <div className="flex items-center justify-between mb-1">
                  <span className={cn('text-xs font-bold', agent.color)}>{agent.name}</span>
                  <span className="text-[9px] font-mono text-[var(--color-text-secondary)] uppercase">
                    {agent.status}
                  </span>
                </div>
                <p className={cn(
                  'text-[11px] font-mono leading-relaxed',
                  isActive ? 'text-[var(--color-text-primary)] animate-pulse' : 'text-[var(--color-text-secondary)]',
                )}>
                  {agent.output}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-4 pt-4 border-t border-[var(--color-border)] flex items-center justify-between">
        <div className="flex flex-col">
          <span className="text-[10px] font-mono text-[var(--color-text-secondary)]">FINAL SYNTHESIS</span>
          <span className={cn(
            'text-lg font-bold tracking-wider',
            summary.decision === 'BUY' ? 'text-[var(--color-success)]' : summary.decision === 'SELL' ? 'text-[var(--color-danger)]' : 'text-[var(--color-warning)]',
          )}>
            {summary.decision} (CONF: {summary.confidence.toFixed(0)}%)
          </span>
        </div>
        <button
          onClick={() => void handleExecute()}
          disabled={submitting || Boolean(data.health?.emergency_stop_active)}
          className="bg-[var(--color-accent)] hover:bg-[var(--color-accent)]/80 text-white text-xs font-bold px-4 py-2 rounded transition-colors disabled:opacity-50"
        >
          {submitting ? 'QUEUING...' : 'EXECUTE ORDER'}
        </button>
      </div>
      <p className="text-[10px] font-mono text-[var(--color-text-secondary)]">
        This panel summarizes saved outputs for operator review. It is not a live token-by-token LLM trace.
      </p>
    </div>
  );
}
