import { useState, useEffect } from 'react';

export interface ChartDataPoint {
  time: string;
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IndicatorData {
  rsi?: number[];
  macd?: {
    macd: number[];
    signal: number[];
    histogram: number[];
  };
  bollinger?: {
    upper: number[];
    middle: number[];
    lower: number[];
  };
}

interface UseChartDataResult {
  data: ChartDataPoint[] | null;
  loading: boolean;
  error: string | null;
}

export function useChartData(
  symbol: string,
  interval: string = '1d',
  range: string = '3mo'
): UseChartDataResult {
  const [data, setData] = useState<ChartDataPoint[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      setLoading(true);
      setError(null);

      try {
        const resp = await fetch(
          `/api/marketdata/history?symbol=${encodeURIComponent(symbol)}&interval=${interval}&range=${range}`
        );
        const json = await resp.json();

        if (cancelled) return;

        if (json.status === 'ok' && json.data) {
          setData(json.data);
        } else {
          setError(json.message || 'Failed to load data');
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Unknown error');
      }

      setLoading(false);
    }

    if (symbol) {
      fetchData();
    }

    return () => {
      cancelled = true;
    };
  }, [symbol, interval, range]);

  return { data, loading, error };
}

export function useIndicators(
  symbol: string,
  interval: string = '1d',
  range: string = '3mo'
): IndicatorData {
  const [data, setData] = useState<IndicatorData>({});

  useEffect(() => {
    async function fetchIndicators() {
      try {
        const resp = await fetch(
          `/api/marketdata/indicators?symbol=${encodeURIComponent(symbol)}&interval=${interval}&range=${range}`
        );
        const json = await resp.json();
        if (json.status === 'ok') {
          setData({
            rsi: json.rsi,
            macd: json.macd,
            bollinger: json.bollinger,
          });
        }
      } catch (e) {
        console.error('Failed to load indicators:', e);
      }
    }

    if (symbol) {
      fetchIndicators();
    }
  }, [symbol, interval, range]);

  return data;
}

export function useQuote(symbol: string) {
  const [quote, setQuote] = useState<{
    price: number;
    change: number;
    change_pct: number;
    volume: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchQuote() {
      setLoading(true);
      try {
        const resp = await fetch(`/api/marketdata/quote?symbol=${encodeURIComponent(symbol)}`);
        const json = await resp.json();
        if (!cancelled && json.status === 'ok') {
          setQuote(json.quote || json);
        }
      } catch (e) {
        console.error('Failed to fetch quote:', e);
      }
      setLoading(false);
    }

    if (symbol) {
      fetchQuote();
      const interval = setInterval(fetchQuote, 60000);
      return () => {
        cancelled = true;
        clearInterval(interval);
      };
    }
  }, [symbol]);

  return { quote, loading };
}

export function useSymbols() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [benchmark, setBenchmark] = useState('SPY');

  useEffect(() => {
    async function fetchSymbols() {
      try {
        const resp = await fetch('/api/marketdata/symbols');
        const json = await resp.json();
        if (json.status === 'ok') {
          setSymbols(json.symbols || []);
          setBenchmark(json.benchmark || 'SPY');
        }
      } catch (e) {
        console.error('Failed to fetch symbols:', e);
      }
    }

    fetchSymbols();
  }, []);

  return { symbols, benchmark };
}
