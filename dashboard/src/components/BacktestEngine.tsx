import { useEffect, useMemo, useState } from 'react';
import { Activity, BrainCircuit, Play, Settings2, Target, TrendingUp } from 'lucide-react';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from 'recharts';
import { cn } from '../lib/utils';
import {
  type DashboardDataBundle,
  formatPercent,
  humanizeStrategyName,
} from '../lib/dashboard-data';

interface BacktestEngineProps {
  data: DashboardDataBundle;
  onRefresh: () => Promise<void>;
}

export function BacktestEngine({ data, onRefresh }: BacktestEngineProps) {
  const strategies = useMemo(() => {
    const config = data.validationReport?.configuration?.strategies ?? {};
    return Object.entries(config).map(([id, entry]) => ({
      id,
      name: humanizeStrategyName(id),
      params: Object.entries(entry)
        .filter(([key]) => key !== 'enabled' && key !== 'weight')
        .map(([name, initial]) => {
          const current = data.experimentReport?.best_experiment?.config_overrides?.strategies?.[id]?.[name];
          return {
            name: humanizeStrategyName(name),
            initial,
            current: current ?? initial,
            optimal: current ?? initial,
          };
        }),
    }));
  }, [data.experimentReport, data.validationReport]);

  const [activeAgent, setActiveAgent] = useState(strategies[0]?.id ?? 'momentum');
  const currentAgentData = strategies.find((agent) => agent.id === activeAgent) ?? strategies[0];

  useEffect(() => {
    if (strategies.length > 0 && !strategies.some((agent) => agent.id === activeAgent)) {
      setActiveAgent(strategies[0].id);
    }
  }, [activeAgent, strategies]);

  const optimizationCurve = useMemo(() => {
    const ranking = data.experimentReport?.ranking ?? [];
    if (ranking.length > 0) {
      return ranking.map((item, index) => ({
        epoch: (index + 1) * 1000,
        reward: Number((((item.metrics?.sharpe_ratio ?? 0) * 10) + ((item.metrics?.alpha ?? 0) * 100)).toFixed(2)),
        drawdown: Number((Math.abs(item.metrics?.max_drawdown ?? 0) * 100).toFixed(2)),
      }));
    }

    return (data.validationReport?.monthly_returns ?? []).map((item, index) => ({
      epoch: (index + 1) * 1000,
      reward: Number(item.return_pct.toFixed(2)),
      drawdown: Number((Math.abs(data.validationReport?.summary?.max_drawdown ?? 0) * 100).toFixed(2)),
    }));
  }, [data.experimentReport, data.validationReport]);

  const scoreWeights = useMemo(() => {
    const objective = data.experimentReport?.objective?.formula ?? '';
    return {
      alpha: objective.includes('alpha') ? 0.55 : 0.25,
      sharpe: objective.includes('sharpe') ? 0.25 : 0.2,
      drawdown: objective.includes('drawdown') || objective.includes('MaxDD') ? 0.15 : 0.25,
      turnover: objective.includes('turnover') ? 0.05 : 0.1,
    };
  }, [data.experimentReport]);

  return (
    <div className="flex flex-col gap-6 max-w-7xl mx-auto pb-10">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text-primary)]">Validation & Experiment Viewer</h2>
          <p className="text-sm text-[var(--color-text-secondary)] font-mono mt-1">
            Inspect saved validation artifacts, experiment rankings, and best-run parameter overrides
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => void onRefresh()}
            className="text-sm font-bold px-4 py-2 rounded transition-colors flex items-center gap-2 bg-[var(--color-success)]/10 text-[var(--color-success)] border border-[var(--color-success)]/30 hover:bg-[var(--color-success)] hover:text-white"
          >
            <Play size={16} />
            REFRESH ARTIFACTS
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="flex flex-col gap-6">
          <div className="panel p-5 flex flex-col gap-4">
            <h3 className="font-semibold text-sm flex items-center gap-2 border-b border-[var(--color-border)] pb-3">
              <Target size={16} className="text-[var(--color-accent)]" />
              Reward Function Definition
            </h3>

            <div className="flex flex-col gap-4">
              <div className="bg-[var(--color-bg)] p-3 rounded border border-[var(--color-border)]">
                <div className="text-[10px] font-mono text-[var(--color-text-secondary)] mb-2">OBJECTIVE FORMULA</div>
                <code className="text-xs font-mono text-[var(--color-accent)] break-all">
                  {data.experimentReport?.objective?.formula ?? 'alpha_pct + sharpe - drawdown_penalty'}
                </code>
              </div>

              <div className="flex flex-col gap-3">
                <MetricSlider label="Alpha Edge" value={scoreWeights.alpha} color="var(--color-success)" />
                <MetricSlider label="Sharpe Quality" value={scoreWeights.sharpe} color="var(--color-accent)" />
                <MetricSlider label="Drawdown Penalty" value={scoreWeights.drawdown} color="var(--color-danger)" />
                <MetricSlider label="Turnover Penalty" value={scoreWeights.turnover} color="var(--color-warning)" />
              </div>
            </div>
          </div>

          <div className="panel p-5 flex flex-col gap-4">
            <h3 className="font-semibold text-sm flex items-center gap-2 border-b border-[var(--color-border)] pb-3">
              <BrainCircuit size={16} className="text-[var(--color-accent)]" />
              Select Agent
            </h3>
            <div className="flex flex-col gap-2">
              {strategies.map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => setActiveAgent(agent.id)}
                  className={cn(
                    'flex items-center justify-between p-3 rounded border text-sm transition-colors',
                    activeAgent === agent.id
                      ? 'bg-[var(--color-accent)]/10 border-[var(--color-accent)]/50 text-[var(--color-accent)]'
                      : 'bg-[var(--color-bg)] border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-text-secondary)]',
                  )}
                >
                  <span className="font-medium">{agent.name}</span>
                  {activeAgent === agent.id && (
                    <Activity size={14} className="animate-pulse" />
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="lg:col-span-2 flex flex-col gap-6">
          <div className="panel p-5 flex flex-col gap-4 h-[300px]">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-sm flex items-center gap-2">
                <TrendingUp size={16} className="text-[var(--color-success)]" />
                Optimization Curve (Score vs Runs)
              </h3>
              <span className="text-xs font-mono text-[var(--color-text-secondary)]">
                Runs: {(data.experimentReport?.successful_experiments ?? optimizationCurve.length).toLocaleString()}
              </span>
            </div>
            <div className="flex-1 min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={optimizationCurve} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" opacity={0.5} />
                  <XAxis
                    dataKey="epoch"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: 'var(--color-text-secondary)', fontFamily: 'var(--font-mono)' }}
                    tickFormatter={(value) => `${value / 1000}k`}
                  />
                  <YAxis
                    yAxisId="left"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: 'var(--color-success)', fontFamily: 'var(--font-mono)' }}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: 'var(--color-danger)', fontFamily: 'var(--font-mono)' }}
                    tickFormatter={(value) => `${value}%`}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: 'var(--color-panel)', borderColor: 'var(--color-border)', borderRadius: '8px', fontFamily: 'var(--font-mono)', fontSize: '12px' }}
                  />
                  <Line yAxisId="left" type="monotone" dataKey="reward" stroke="var(--color-success)" strokeWidth={2} dot={false} name="Optimization Score" />
                  <Line yAxisId="right" type="monotone" dataKey="drawdown" stroke="var(--color-danger)" strokeWidth={2} dot={false} name="Max Drawdown" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="panel p-5 flex flex-col gap-4 flex-1">
            <div className="flex items-center justify-between border-b border-[var(--color-border)] pb-3">
              <h3 className="font-semibold text-sm flex items-center gap-2">
                <Settings2 size={16} className="text-[var(--color-accent)]" />
                Live Parameter Adaptation: {currentAgentData?.name ?? 'Unavailable'}
              </h3>
              <span className="text-[10px] font-mono bg-[var(--color-panel-hover)] px-2 py-1 rounded">
                {data.experimentReport?.best_experiment?.name ?? 'VALIDATION MODE'}
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-secondary)] bg-[var(--color-bg)]/50">
                    <th className="p-3 font-medium">PARAMETER</th>
                    <th className="p-3 font-medium">BASELINE</th>
                    <th className="p-3 font-medium">INITIAL</th>
                    <th className="p-3 font-medium text-[var(--color-accent)]">CURRENT (BEST RUN)</th>
                    <th className="p-3 font-medium text-right">VALIDATION NOTE</th>
                  </tr>
                </thead>
                <tbody className="text-sm font-mono">
                  {(currentAgentData?.params ?? []).map((param, index) => (
                    <tr key={index} className="border-b border-[var(--color-border)]/50 hover:bg-[var(--color-panel-hover)] transition-colors">
                      <td className="p-3 font-bold text-[var(--color-text-primary)]">{param.name}</td>
                      <td className="p-3 text-[var(--color-text-secondary)]">
                        {String(param.initial)}
                      </td>
                      <td className="p-3 text-[var(--color-text-secondary)]">{String(param.initial)}</td>
                      <td className="p-3 text-[var(--color-accent)] font-bold flex items-center gap-2">
                        {String(param.current)}
                        {String(param.current) !== String(param.initial) && <Activity size={12} className="animate-pulse opacity-50" />}
                      </td>
                      <td className="p-3 text-right text-[var(--color-success)]">
                        {formatPercent(data.validationReport?.benchmark_comparison?.alpha_pct)}
                      </td>
                    </tr>
                  ))}
                  {(!currentAgentData || currentAgentData.params.length === 0) && (
                    <tr>
                      <td colSpan={5} className="p-4 text-center text-[var(--color-text-secondary)]">
                        No parameter overrides were recorded for the selected strategy.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

interface MetricSliderProps {
  label: string;
  value: number;
  color: string;
}

function MetricSlider({ label, value, color }: MetricSliderProps) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs font-mono">
        <span style={{ color }}>{label}</span>
        <span>{value.toFixed(2)}</span>
      </div>
      <input type="range" min="0" max="1" step="0.05" value={value} readOnly style={{ accentColor: color }} />
    </div>
  );
}
