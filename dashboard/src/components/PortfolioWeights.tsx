import { useMemo } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { PieChart as PieChartIcon } from 'lucide-react';
import { type DashboardDataBundle } from '../lib/dashboard-data';
import { cn } from '../lib/utils';

interface PortfolioWeightsProps {
  data: DashboardDataBundle;
}

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4'];

export function PortfolioWeights({ data }: PortfolioWeightsProps) {
  const chartData = useMemo(() => {
    const strategies = data.strategyDrilldown?.strategies ?? [];
    if (strategies.length === 0) {
      return [{ name: 'Cash/Idle', value: 100 }];
    }
    
    return strategies.map((s, idx) => ({
      name: s.name.replace('_', ' ').toUpperCase(),
      value: Number((s.runtime_weight * 100).toFixed(2)),
      color: COLORS[idx % COLORS.length]
    })).filter(d => d.value > 0);
  }, [data.strategies]);

  return (
    <div className="panel p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between border-b border-[var(--color-border)] pb-3">
        <h3 className="font-semibold text-sm flex items-center gap-2">
          <PieChartIcon size={16} className="text-[var(--color-accent)]" />
          Optimal Portfolio Allocation (Risk Parity)
        </h3>
      </div>
      
      <div className="flex-1 min-h-[250px] relative">
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={80}
                paddingAngle={5}
                dataKey="value"
                stroke="none"
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: 'var(--color-bg)', 
                  borderColor: 'var(--color-border)',
                  borderRadius: '4px',
                  fontFamily: 'monospace',
                  fontSize: '12px'
                }}
                itemStyle={{ color: 'var(--color-text-primary)' }}
                formatter={(value: number) => [`${value}%`, 'Weight']}
              />
              <Legend 
                verticalAlign="bottom" 
                height={36} 
                iconType="circle"
                formatter={(value) => <span className="text-[10px] font-mono text-[var(--color-text-secondary)]">{value}</span>}
              />
            </PieChart>
          </ResponsiveContainer>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-xs font-mono text-[var(--color-text-secondary)]">
            Awaiting Strategy Optimization...
          </div>
        )}
      </div>
    </div>
  );
}
