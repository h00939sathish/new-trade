import { useMemo } from 'react';
import { Activity, ArrowRight, BarChart2, BrainCircuit, Cpu, Database, GitMerge, Shield, Target } from 'lucide-react';
import { cn } from '../lib/utils';
import {
  clamp,
  type DashboardDataBundle,
  formatPercent,
  humanizeStrategyName,
} from '../lib/dashboard-data';

interface Layer1SignalsProps {
  data: DashboardDataBundle;
}

interface StrategyCard {
  name: string;
  weight: number;
  configuredWeight: number;
  signal: 'BUY' | 'HOLD' | 'SELL';
  strength: number;
  desc: string;
  reward: string;
  epoch: string;
  confidence: number;
  grossPnl: number;
  winRatePct: number;
}

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  momentum: 'SMA Cross + RSI + Trend Follow',
  mean_reversion: 'BB Break + RSI Oversold',
  news_driven: 'Sentiment + Headline Reaction',
  volatility_breakout: 'Range Expansion + Vol Spike',
  defensive: 'High Volatility Filter + Capital Defense',
};

const DEFAULT_STRATEGY_WEIGHTS: Record<string, number> = {
  momentum: 0.35,
  mean_reversion: 0.3,
  volatility_breakout: 0.15,
  news_driven: 0.1,
  defensive: 0.1,
};

export function Layer1Signals({ data }: Layer1SignalsProps) {
  const strategies = useMemo<StrategyCard[]>(() => {
    const drilldownMap = new Map(
      (data.strategyDrilldown?.strategies ?? []).map((strategy) => [strategy.name, strategy]),
    );
    const configStrategies = data.validationReport?.configuration?.strategies
      ?? Object.fromEntries(
        Object.entries(DEFAULT_STRATEGY_WEIGHTS).map(([name, weight]) => [name, { enabled: true, weight }]),
      );
    const participation = new Map(
      (data.validationReport?.strategy_participation ?? []).map((row) => [row.strategy, row]),
    );
    const sentimentValues = Object.values(data.analysisResults?.sentiment ?? {});
    const averageSentiment = sentimentValues.length > 0
      ? sentimentValues.reduce((sum, row) => sum + row.score, 0) / sentimentValues.length
      : 0;

    return Object.entries(configStrategies)
    .filter(([name, config]) => drilldownMap.get(name)?.enabled ?? config?.enabled !== false)
    .map(([name, config]) => {
      const drilldown = drilldownMap.get(name);
      const validation = drilldown?.validation ?? participation.get(name);
      const recentActivity = drilldown?.recent_activity;
      const confidence = validation?.avg_confidence ?? (name === 'news_driven' ? 0.55 + averageSentiment : 0.5);
      const scoreBase = name === 'news_driven'
        ? averageSentiment * 100
        : (confidence - 0.5) * 100;
      const signal = scoreBase > 12 ? 'BUY' : scoreBase < -8 ? 'SELL' : 'HOLD';
      const weight = Number(
        drilldown?.runtime_weight ?? config.weight ?? DEFAULT_STRATEGY_WEIGHTS[name] ?? 0,
      ) * 100;
      const configuredWeight = Number(
        drilldown?.configured_weight ?? config.weight ?? DEFAULT_STRATEGY_WEIGHTS[name] ?? 0,
      ) * 100;
      const strength = clamp((confidence * 100) + (weight * 0.35), 18, 95);
      const recentTradeCount = recentActivity?.recent_trades ?? validation?.trades ?? 0;
      const grossPnl = Number(recentActivity?.gross_pnl ?? validation?.gross_value ?? 0);
      const winRatePct = Number(recentActivity?.win_rate_pct ?? 0);
      const reward = grossPnl
        ? `${grossPnl >= 0 ? '+' : ''}${(grossPnl / 1000).toFixed(1)}k`
        : `Conf ${(confidence * 100).toFixed(0)}%`;

      return {
        name,
        weight,
        configuredWeight,
        signal,
        strength,
        desc: STRATEGY_DESCRIPTIONS[name] ?? 'Control-plane strategy drilldown',
        reward,
        epoch: recentTradeCount > 0 ? `Trades: ${recentTradeCount} · Win ${winRatePct.toFixed(0)}%` : 'No recent trades',
        confidence,
        grossPnl,
        winRatePct,
      };
    }).sort((left, right) => right.weight - left.weight);
  }, [data.analysisResults, data.strategyDrilldown, data.validationReport]);

  const aggregate = useMemo(() => {
    if (strategies.length === 0) {
      return { label: 'NO SIGNAL', confidence: 0, numeric: 0 };
    }

    const numeric = strategies.reduce((sum, strategy) => {
      const direction = strategy.signal === 'BUY' ? 1 : strategy.signal === 'SELL' ? -1 : 0;
      return sum + ((strategy.weight / 100) * direction * strategy.confidence);
    }, 0);

    if (numeric > 0.55) {
      return { label: 'STRONG BUY', confidence: clamp(numeric * 100, 0, 100), numeric };
    }
    if (numeric > 0.18) {
      return { label: 'BUY', confidence: clamp(numeric * 100, 0, 100), numeric };
    }
    if (numeric < -0.35) {
      return { label: 'SELL', confidence: clamp(Math.abs(numeric) * 100, 0, 100), numeric };
    }
    return { label: 'HOLD', confidence: clamp(Math.abs(numeric) * 100, 0, 100), numeric };
  }, [strategies]);

  const activeRegime = useMemo(() => {
    const regimes = data.validationReport?.regime_breakdown ?? [];
    if (regimes.length === 0) {
      return 'UNKNOWN';
    }
    const dominant = [...regimes].sort((left, right) => {
      if (right.days !== left.days) {
        return right.days - left.days;
      }
      return right.avg_daily_return_pct - left.avg_daily_return_pct;
    })[0];
    return dominant.regime.replace('_', ' ').toUpperCase();
  }, [data.validationReport]);

  const riskConfig = data.validationReport?.configuration?.risk_management;
  const portfolioMethod = data.validationReport?.configuration?.portfolio?.method;
  const alphaPct = data.validationReport?.benchmark_comparison?.alpha_pct ?? null;

  return (
    <div className="panel p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between border-b border-[var(--color-border)] pb-3">
        <h3 className="font-semibold text-sm flex items-center gap-2">
          <Cpu size={16} className="text-[var(--color-accent)]" />
          Layer 1: RL-Optimized Signal Pipeline
        </h3>
        <div className="flex gap-2">
          <span className="text-[10px] font-mono bg-[var(--color-accent)]/10 text-[var(--color-accent)] px-2 py-1 rounded flex items-center gap-1 border border-[var(--color-accent)]/20">
            <BrainCircuit size={12} className="animate-pulse" /> ARTIFACT SYNC
          </span>
          <span className="text-[10px] font-mono bg-[var(--color-success)]/10 text-[var(--color-success)] px-2 py-1 rounded border border-[var(--color-success)]/20">
            REGIME: {activeRegime}
          </span>
        </div>
      </div>

      <div className="flex items-center justify-between text-[10px] font-mono text-[var(--color-text-secondary)] mb-2 px-2">
        <div className="flex flex-col items-center gap-1"><Database size={14} /> Ingestion</div>
        <ArrowRight size={12} className="opacity-30" />
        <div className="flex flex-col items-center gap-1"><BarChart2 size={14} /> Features</div>
        <ArrowRight size={12} className="opacity-30" />
        <div className="flex flex-col items-center gap-1 text-[var(--color-accent)]"><Activity size={14} /> Regime</div>
        <ArrowRight size={12} className="opacity-30" />
        <div className="flex flex-col items-center gap-1"><GitMerge size={14} /> Agents</div>
        <ArrowRight size={12} className="opacity-30" />
        <div className="flex flex-col items-center gap-1"><Shield size={14} /> Risk</div>
        <ArrowRight size={12} className="opacity-30" />
        <div className="flex flex-col items-center gap-1"><Target size={14} /> Exec</div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
        <div className="flex flex-col gap-2">
          <h4 className="text-xs font-mono text-[var(--color-text-secondary)] mb-1">
            STRATEGY AGENTS ({strategies.length})
          </h4>
          {strategies.map((strategy) => (
            <div key={strategy.name} className="flex items-center justify-between bg-[var(--color-bg)] p-2 rounded border border-[var(--color-border)]">
              <div className="flex flex-col">
                <span className="text-xs font-medium flex items-center gap-1">
                  {humanizeStrategyName(strategy.name)}
                  {strategy.name !== 'news_driven' && <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-accent)] animate-pulse" title="Adaptive strategy"></span>}
                </span>
                <span className="text-[9px] text-[var(--color-text-secondary)] font-mono">{strategy.desc}</span>
                <div className="flex items-center gap-2 mt-1 text-[8px] font-mono text-[var(--color-text-secondary)]">
                  <span className="text-[var(--color-success)]">R: {strategy.reward}</span>
                  <span>{strategy.epoch}</span>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex flex-col items-end">
                  <span className={cn(
                    'text-[10px] font-bold px-1.5 py-0.5 rounded',
                    strategy.signal === 'BUY' ? 'bg-[var(--color-success)]/20 text-[var(--color-success)]' :
                    strategy.signal === 'SELL' ? 'bg-[var(--color-danger)]/20 text-[var(--color-danger)]' :
                    'bg-[var(--color-warning)]/20 text-[var(--color-warning)]',
                  )}>
                    {strategy.signal}
                  </span>
                  <span className="text-[9px] font-mono text-[var(--color-text-secondary)] mt-0.5">
                    W: {formatPercent(strategy.weight, 0)} · Base {formatPercent(strategy.configuredWeight, 0)}
                  </span>
                </div>
                <div className="w-12 h-1.5 bg-[var(--color-border)] rounded-full overflow-hidden">
                  <div
                    className={cn(
                      'h-full rounded-full',
                      strategy.strength > 60 ? 'bg-[var(--color-success)]' : strategy.strength < 40 ? 'bg-[var(--color-danger)]' : 'bg-[var(--color-warning)]',
                    )}
                    style={{ width: `${strategy.strength}%` }}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <h4 className="text-xs font-mono text-[var(--color-text-secondary)] mb-1">AGGREGATED SIGNAL</h4>
            <div className={cn(
              'bg-[var(--color-bg)] p-4 rounded border border-[var(--color-border)] flex flex-col items-center justify-center gap-2 relative overflow-hidden',
              aggregate.numeric > 0.15 ? 'border-[var(--color-success)]/30' : aggregate.numeric < -0.15 ? 'border-[var(--color-danger)]/30' : '',
            )}>
              <div className={cn(
                'absolute inset-0 blur-xl',
                aggregate.numeric > 0.15 ? 'bg-[var(--color-success)]/5' : aggregate.numeric < -0.15 ? 'bg-[var(--color-danger)]/5' : 'bg-[var(--color-accent)]/5',
              )}></div>
              <span className={cn(
                'text-3xl font-bold tracking-widest',
                aggregate.numeric > 0.15 ? 'text-[var(--color-success)]' : aggregate.numeric < -0.15 ? 'text-[var(--color-danger)]' : 'text-[var(--color-warning)]',
              )}>
                {aggregate.label}
              </span>
              <span className="text-xs font-mono text-[var(--color-text-secondary)]">
                CONFIDENCE: {aggregate.confidence.toFixed(0)}%
              </span>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <h4 className="text-xs font-mono text-[var(--color-text-secondary)] mb-1 flex justify-between">
              <span>RISK & RL REWARD FUNCTION</span>
              <span className="text-[var(--color-accent)]">
                alpha={alphaPct !== null ? formatPercent(alphaPct) : '--'}
              </span>
            </h4>
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-[var(--color-bg)] p-2 rounded border border-[var(--color-border)] flex flex-col">
                <span className="text-[10px] font-mono text-[var(--color-text-secondary)]">RL OBJECTIVE</span>
                <span className="text-xs font-medium text-[var(--color-accent)]">
                  {(data.experimentReport?.objective?.name ?? 'balanced_alpha').replaceAll('_', ' ').toUpperCase()}
                </span>
              </div>
              <div className="bg-[var(--color-bg)] p-2 rounded border border-[var(--color-border)] flex flex-col">
                <span className="text-[10px] font-mono text-[var(--color-text-secondary)]">RL PENALTY</span>
                <span className="text-xs font-medium text-[var(--color-danger)]">
                  DD &gt; {riskConfig?.max_drawdown_pct ? formatPercent(riskConfig.max_drawdown_pct, 0, 100) : '10%'}
                </span>
              </div>
              <div className="bg-[var(--color-bg)] p-2 rounded border border-[var(--color-border)] flex flex-col">
                <span className="text-[10px] font-mono text-[var(--color-text-secondary)]">ATR TRAILING STOP</span>
                <span className="text-xs font-medium text-[var(--color-success)]">
                  ACTIVE ({riskConfig?.atr_volatility_multiple ? `${riskConfig.atr_volatility_multiple.toFixed(1)}x` : '1.5x'})
                </span>
              </div>
              <div className="bg-[var(--color-bg)] p-2 rounded border border-[var(--color-border)] flex flex-col">
                <span className="text-[10px] font-mono text-[var(--color-text-secondary)]">PORTFOLIO OPT</span>
                <span className="text-xs font-medium text-[var(--color-accent)]">
                  {(portfolioMethod ?? 'risk_parity').replaceAll('_', ' ').toUpperCase()}
                </span>
              </div>
              <div className="bg-[var(--color-bg)] p-2 rounded border border-[var(--color-border)] flex flex-col">
                <span className="text-[10px] font-mono text-[var(--color-text-secondary)]">STRATEGY DRILLDOWN</span>
                <span className="text-xs font-medium text-white">
                  {data.strategyDrilldown?.strategies?.length ?? strategies.length} ACTIVE PATHS
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
