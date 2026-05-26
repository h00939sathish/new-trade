import { useState, useEffect, useMemo } from 'react';
import {
  createChart,
  ColorType,
  CrosshairMode,
 CandlestickSeries,
  LineSeries,
  HistogramSeries,
} from 'lightweight-charts';
import { useChartData } from '../lib/hooks';

interface PriceChartProps {
  symbol: string;
  interval?: '1m' | '5m' | '15m' | '1h' | '1d' | '1w';
  range?: '1w' | '1m' | '3mo' | '1y' | '5y';
}

export function PriceChart({ 
  symbol, 
  interval = '1d', 
  range = '3mo' 
}: PriceChartProps) {
  const [chartContainer, setChartContainer] = useState<HTMLDivElement | null>(null);
  const [chart, setChart] = useState<ReturnType<typeof createChart> | null>(null);
  const { data, loading, error } = useChartData(symbol, interval, range);

  useEffect(() => {
    if (!chartContainer) return;

    const newChart = createChart(chartContainer, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.1)',
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.1)',
      },
    });

    const candlestickSeries = newChart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });

    const volumeSeries = newChart.addSeries(HistogramSeries, {
      color: '#3b82f6',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });

    newChart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    setChart(newChart);

    return () => {
      newChart.remove();
    };
  }, [chartContainer]);

  useEffect(() => {
    if (!chart || !data || data.length === 0) return;

    const candlestickData = data.map(d => ({
      time: d.time as any,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));

    const volumeData = data.map(d => ({
      time: d.time as any,
      value: d.volume,
      color: d.close >= d.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)',
    }));

    const cs = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });
    cs.setData(candlestickData);

    const vs = chart.addSeries(HistogramSeries, {
      color: '#3b82f6',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    vs.setData(volumeData);

    chart.timeScale().fitContent();
  }, [chart, data]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--color-accent)]"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-[var(--color-danger)]">
        Error: {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-2 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold">{symbol}</span>
          {data && data.length > 0 && (
            <span className={`text-sm ${data[data.length - 1].close >= data[data.length - 1].open ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}`}>
              Rs.{data[data.length - 1].close.toFixed(2)}
            </span>
          )}
        </div>
        <div className="flex gap-1">
          {['1D', '1W', '1M', '3M', '1Y'].map((r) => (
            <button
              key={r}
              className="px-2 py-1 text-xs rounded bg-[var(--color-panel)] hover:bg-[var(--color-border)]"
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      <div ref={setChartContainer} className="flex-1" />
    </div>
  );
}
