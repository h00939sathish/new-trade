import { useMemo } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  type PaperReport,
  type ValidationReport,
  formatCurrency,
  formatTimestampLabel,
} from '../lib/dashboard-data';

interface EquityChartProps {
  paperReport: PaperReport | null;
  validationReport: ValidationReport | null;
}

export function EquityChart({ paperReport, validationReport }: EquityChartProps) {
  const data = useMemo(() => {
    const curve = paperReport?.equity_curve ?? [];
    if (curve.length === 0) {
      const baseline = validationReport?.summary?.initial_capital ?? 1_000_000;
      return [{ date: 'No data', equity: baseline, benchmark: baseline }];
    }

    const sampled = curve.length > 60
      ? curve.filter((_, index) => index % Math.ceil(curve.length / 60) === 0)
      : curve;

    const benchmarkFinal = validationReport?.benchmark_comparison?.final_benchmark_value
      ?? validationReport?.summary?.initial_capital
      ?? sampled[sampled.length - 1].portfolio_value;
    const benchmarkStart = paperReport?.summary.initial_capital ?? sampled[0].portfolio_value;

    return sampled.map((point, index) => {
      const ratio = sampled.length > 1 ? index / (sampled.length - 1) : 0;
      const benchmark = benchmarkStart + ((benchmarkFinal - benchmarkStart) * ratio);
      return {
        date: formatTimestampLabel(point.timestamp, sampled.length > 20),
        equity: point.portfolio_value,
        benchmark,
      };
    });
  }, [paperReport, validationReport]);

  const yDomain = useMemo(() => {
    const values = data.flatMap((point) => [point.equity, point.benchmark]);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const padding = Math.max((max - min) * 0.12, 10_000);
    return [min - padding, max + padding] as const;
  }, [data]);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 10, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--color-accent)" stopOpacity={0.3} />
            <stop offset="95%" stopColor="var(--color-accent)" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="colorBench" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--color-text-secondary)" stopOpacity={0.1} />
            <stop offset="95%" stopColor="var(--color-text-secondary)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="date"
          axisLine={false}
          tickLine={false}
          tick={{ fontSize: 10, fill: 'var(--color-text-secondary)', fontFamily: 'var(--font-mono)' }}
          dy={10}
          minTickGap={30}
        />
        <YAxis
          domain={yDomain}
          axisLine={false}
          tickLine={false}
          tick={{ fontSize: 10, fill: 'var(--color-text-secondary)', fontFamily: 'var(--font-mono)' }}
          tickFormatter={(value) => `₹${(value / 100000).toFixed(1)}L`}
          dx={-10}
        />
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" opacity={0.5} />
        <Tooltip
          contentStyle={{
            backgroundColor: 'var(--color-panel)',
            borderColor: 'var(--color-border)',
            borderRadius: '8px',
            fontFamily: 'var(--font-mono)',
            fontSize: '12px',
          }}
          itemStyle={{ color: 'var(--color-text-primary)' }}
          formatter={(value: number, name: string) => [formatCurrency(value), name === 'benchmark' ? 'Benchmark' : 'Alpha System']}
        />
        <Area
          type="monotone"
          dataKey="benchmark"
          stroke="var(--color-text-secondary)"
          strokeWidth={2}
          fillOpacity={1}
          fill="url(#colorBench)"
          name={validationReport?.configuration?.benchmark ?? 'Benchmark'}
        />
        <Area
          type="monotone"
          dataKey="equity"
          stroke="var(--color-accent)"
          strokeWidth={2}
          fillOpacity={1}
          fill="url(#colorEquity)"
          name="Alpha System"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
