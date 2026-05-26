import { useCallback, useEffect, useMemo, useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { Dashboard } from './components/Dashboard';
import { LiveTrading } from './components/LiveTrading';
import { Settings } from './components/Settings';
import { BacktestEngine } from './components/BacktestEngine';
import { Connectivity } from './components/Connectivity';
import { BrokerStatus } from './components/BrokerStatus';
import {
  type AnalysisResults,
  type DashboardDataBundle,
  type ExperimentReport,
  fetchJson,
  type HealthSnapshot,
  type OverviewSnapshot,
  type OrderListResponse,
  type PaperReport,
  type StrategyDrilldownReport,
  type ValidationReport,
} from './lib/dashboard-data';

const REFRESH_INTERVAL_MS = 15_000;

export default function App() {
  const [currentTab, setCurrentTab] = useState('dashboard');
  const [data, setData] = useState<DashboardDataBundle>({
    paperReport: null,
    liveReport: null,
    validationReport: null,
    analysisResults: null,
    experimentReport: null,
    strategyDrilldown: null,
    pendingOrders: [],
    health: null,
    overview: null,
    lastUpdated: null,
    loading: true,
    error: null,
  });

  const refresh = useCallback(async () => {
    try {
      const [
        paperReport,
        liveReport,
        validationReport,
        analysisResults,
        experimentReport,
        pendingOrders,
        strategyDrilldown,
        health,
        overview,
      ] = await Promise.allSettled([
        fetchJson<PaperReport>('/api/paper-report'),
        fetchJson<PaperReport>('/api/live-report'),
        fetchJson<ValidationReport>('/api/output/validation_report'),
        fetchJson<AnalysisResults>('/api/output/analysis_results'),
        fetchJson<ExperimentReport>('/api/output/experiment_report'),
        fetchJson<OrderListResponse>('/api/orders/pending'),
        fetchJson<StrategyDrilldownReport>('/api/control-plane/strategies'),
        fetchJson<HealthSnapshot>('/health'),
        fetchJson<OverviewSnapshot>('/api/control-plane/overview'),
      ]);

      setData({
        paperReport: paperReport.status === 'fulfilled' ? paperReport.value : null,
        liveReport: liveReport.status === 'fulfilled' ? liveReport.value : null,
        validationReport: validationReport.status === 'fulfilled' ? validationReport.value : null,
        analysisResults: analysisResults.status === 'fulfilled' ? analysisResults.value : null,
        experimentReport: experimentReport.status === 'fulfilled' ? experimentReport.value : null,
        strategyDrilldown: strategyDrilldown.status === 'fulfilled' ? strategyDrilldown.value : null,
        pendingOrders: pendingOrders.status === 'fulfilled' && Array.isArray(pendingOrders.value?.orders)
          ? pendingOrders.value.orders
          : [],
        health: health.status === 'fulfilled' ? health.value : null,
        overview: overview.status === 'fulfilled' ? overview.value : null,
        lastUpdated: new Date().toISOString(),
        loading: false,
        error: null,
      });
    } catch (error) {
      setData((current) => ({
        ...current,
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to refresh dashboard data',
      }));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      if (!cancelled) {
        await refresh();
      }
    };

    void run();
    const intervalId = window.setInterval(() => {
      void run();
    }, REFRESH_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [refresh]);

  const systemStatus = useMemo(() => {
    if (data.health?.emergency_stop_active) {
      return 'HALTED';
    }
    if (data.loading) {
      return 'SYNCING';
    }
    if (data.health?.status) {
      return data.health.status.toUpperCase();
    }
    return 'ONLINE';
  }, [data.health, data.loading]);

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--color-bg)] text-[var(--color-text-primary)]">
      <Sidebar currentTab={currentTab} setCurrentTab={setCurrentTab} systemStatus={systemStatus} />
      <main className="flex-1 overflow-y-auto p-6">
        {currentTab === 'dashboard' && <Dashboard data={data} onRefresh={refresh} />}
        {currentTab === 'live-paper' && <LiveTrading data={data} onRefresh={refresh} mode="paper" />}
        {currentTab === 'live-money' && <LiveTrading data={data} onRefresh={refresh} mode="live" />}
        {currentTab === 'backtest' && <BacktestEngine data={data} onRefresh={refresh} />}
        {currentTab === 'connectivity' && <Connectivity data={data} />}
        {currentTab === 'broker' && <BrokerStatus data={data} />}
        {currentTab === 'settings' && <Settings overview={data.overview} health={data.health} />}
        {currentTab !== 'dashboard' && currentTab !== 'live-paper' && currentTab !== 'live-money' && currentTab !== 'backtest' && currentTab !== 'connectivity' && currentTab !== 'broker' && currentTab !== 'settings' && (
          <div className="flex items-center justify-center h-full text-[var(--color-text-secondary)]">
            {currentTab.charAt(0).toUpperCase() + currentTab.slice(1)} Module - Coming Soon
          </div>
        )}
      </main>
    </div>
  );
}
