import { useMemo } from 'react';
import { useChartData, useIndicators, IndicatorData } from '../lib/hooks';

interface IndicatorPanelProps {
  symbol: string;
  interval?: string;
  range?: string;
}

export function IndicatorPanel({ symbol, interval = '1d', range = '3mo' }: IndicatorPanelProps) {
  const { data } = useChartData(symbol, interval, range);
  const indicators = useIndicators(symbol, interval, range);

  const currentRSI = useMemo(() => {
    if (!indicators.rsi || indicators.rsi.length === 0) return null;
    return indicators.rsi[indicators.rsi.length - 1];
  }, [indicators.rsi]);

  const currentMACD = useMemo(() => {
    if (!indicators.macd || !indicators.macd.macd || indicators.macd.macd.length === 0) return null;
    const idx = indicators.macd.macd.length - 1;
    return {
      macd: indicators.macd.macd[idx],
      signal: indicators.macd.signal[idx],
      histogram: indicators.macd.histogram[idx],
    };
  }, [indicators.macd]);

  const rsiColor = useMemo(() => {
    if (currentRSI === null) return 'text-[var(--color-text-secondary)]';
    if (currentRSI > 70) return 'text-[var(--color-danger)]';
    if (currentRSI < 30) return 'text-[var(--color-success)]';
    return 'text-[var(--color-text-primary)]';
  }, [currentRSI]);

  const macdColor = useMemo(() => {
    if (currentMACD === null) return 'text-[var(--color-text-secondary)]';
    return currentMACD.histogram >= 0 ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]';
  }, [currentMACD]);

  return (
    <div className="grid grid-cols-3 gap-4 p-4">
      <div className="bg-[var(--color-panel)] rounded-lg p-4">
        <div className="text-sm text-[var(--color-text-secondary)] mb-1">RSI (14)</div>
        <div className={`text-2xl font-mono font-bold ${rsiColor}`}>
          {currentRSI !== null ? currentRSI.toFixed(1) : '--'}
        </div>
        <div className="text-xs text-[var(--color-text-secondary)] mt-2">
          {currentRSI !== null && (
            <>
              {currentRSI > 70 ? 'Overbought' : currentRSI < 30 ? 'Oversold' : 'Neutral'}
            </>
          )}
        </div>
      </div>

      <div className="bg-[var(--color-panel)] rounded-lg p-4">
        <div className="text-sm text-[var(--color-text-secondary)] mb-1">MACD (12,26,9)</div>
        <div className={`text-xl font-mono font-bold ${macdColor}`}>
          {currentMACD !== null ? currentMACD.macd.toFixed(2) : '--'}
        </div>
        <div className="text-xs text-[var(--color-text-secondary)] mt-2">
          Signal: {currentMACD !== null ? currentMACD.signal.toFixed(2) : '--'}
        </div>
      </div>

      <div className="bg-[var(--color-panel)] rounded-lg p-4">
        <div className="text-sm text-[var(--color-text-secondary)] mb-1">Bollinger Bands</div>
        {indicators.bollinger && data && data.length > 0 ? (
          <>
            <div className="text-sm font-mono">
              <span className="text-[var(--color-success)]">
                {indicators.bollinger.upper[indicators.bollinger.upper.length - 1]?.toFixed(0)}
              </span>
              {' / '}
              <span className="text-[var(--color-text-primary)]">
                {indicators.bollinger.middle[indicators.bollinger.middle.length - 1]?.toFixed(0)}
              </span>
              {' / '}
              <span className="text-[var(--color-danger)]">
                {indicators.bollinger.lower[indicators.bollinger.lower.length - 1]?.toFixed(0)}
              </span>
            </div>
            <div className="text-xs text-[var(--color-text-secondary)] mt-2">
              Current: Rs.{data[data.length - 1].close.toFixed(0)}
            </div>
          </>
        ) : (
          <div className="text-[var(--color-text-secondary)]">--</div>
        )}
      </div>
    </div>
  );
}
