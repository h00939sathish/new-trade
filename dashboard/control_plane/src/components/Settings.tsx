import { useEffect, useState } from 'react';
import { Key, Save, Server, Settings2, Shield, Wifi, WifiOff } from 'lucide-react';
import { cn } from '../lib/utils';
import {
  buildAuthHeaders,
  clearOperatorAuthToken,
  getOperatorAuthToken,
  setOperatorAuthToken,
  type HealthSnapshot,
  type OverviewSnapshot,
} from '../lib/dashboard-data';

interface SettingsProps {
  overview: OverviewSnapshot | null;
  health: HealthSnapshot | null;
}

export function Settings({ overview, health }: SettingsProps) {
  const [configuringBroker, setConfiguringBroker] = useState<string | null>(null);
  const [configuredKeys, setConfiguredKeys] = useState<Record<string, string>>({});
  const [operatorToken, setOperatorToken] = useState(() => getOperatorAuthToken());
  const [tokenStatus, setTokenStatus] = useState<string | null>(null);
  const [formValues, setFormValues] = useState({
    apiKey: '',
    apiSecret: '',
    clientCode: '',
    totpSecret: '',
    env: 'PAPER',
  });

  const loadConfiguredKeys = async () => {
    try {
      const res = await fetch('/api/settings/keys', {
        headers: buildAuthHeaders(),
      });
      if (!res.ok) {
        throw new Error(`settings fetch returned ${res.status}`);
      }
      const rows = await res.json();
      const keysMap: Record<string, string> = {};
      rows.forEach((row: any) => {
        keysMap[row.broker] = row.env;
      });
      setConfiguredKeys(keysMap);
      setTokenStatus('Protected control-plane routes are authenticated.');
    } catch (err) {
      console.error('Failed to load keys', err);
      setConfiguredKeys({});
      setTokenStatus('Enter a valid operator token to use broker settings, manual execution, and approvals.');
    }
  };

  useEffect(() => {
    void loadConfiguredKeys();
  }, []);

  const handleSaveOperatorToken = async () => {
    const trimmed = operatorToken.trim();
    if (!trimmed) {
      setTokenStatus('Operator token cannot be empty.');
      return;
    }
    setOperatorAuthToken(trimmed);
    setTokenStatus('Operator token saved to local storage for this browser.');
    await loadConfiguredKeys();
  };

  const handleClearOperatorToken = () => {
    clearOperatorAuthToken();
    setOperatorToken('');
    setConfiguredKeys({});
    setTokenStatus('Operator token cleared.');
  };

  const handleSaveBroker = async (brokerName: string) => {
    try {
      const res = await fetch('/api/settings/keys', {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          broker: brokerName,
          apiKey: formValues.apiKey,
          apiSecret: formValues.apiSecret,
          clientCode: formValues.clientCode,
          totpSecret: formValues.totpSecret,
          env: formValues.env,
        }),
      });
      if (res.ok) {
        setConfiguredKeys((prev) => ({ ...prev, [brokerName]: formValues.env }));
        setConfiguringBroker(null);
        setFormValues({ apiKey: '', apiSecret: '', clientCode: '', totpSecret: '', env: 'PAPER' });
        setTokenStatus(`Saved credentials for ${brokerName}.`);
      } else {
        window.alert('Failed to save credentials');
      }
    } catch (err) {
      console.error(err);
      window.alert('Error saving credentials');
    }
  };

  const activeBrokerName = overview?.broker?.name?.toLowerCase();
  const activeBrokerEnv = overview?.broker?.allow_live_orders ? 'LIVE' : 'PAPER';
  const brokerHealth = overview?.health?.broker_health ?? health?.broker_health;
  const reconciliation = overview?.health?.reconciliation ?? health?.reconciliation;

  const brokers = [
    { id: 'groww', name: 'Groww', type: 'NSE Equities' },
    { id: 'angel_one', name: 'Angel One', type: 'Indian Equities & F&O' },
    { id: 'alpaca', name: 'Alpaca', type: 'US Equities' },
    { id: 'binance', name: 'Binance', type: 'Crypto' },
  ].map((broker) => ({
    ...broker,
    status: configuredKeys[broker.name] ? 'connected' : activeBrokerName === broker.id ? 'connected' : 'disconnected',
    env: configuredKeys[broker.name] || (activeBrokerName === broker.id ? activeBrokerEnv : broker.id === 'angel_one' ? 'LIVE' : 'PAPER'),
  }));

  return (
    <div className="flex flex-col gap-6 max-w-7xl mx-auto pb-10">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text-primary)]">Platform Settings</h2>
          <p className="text-sm text-[var(--color-text-secondary)] font-mono mt-1">
            Broker secrets stay in server memory for the current process; persistent broker auth should come from environment variables
          </p>
        </div>
        <div className="bg-[var(--color-panel-hover)] text-[var(--color-text-secondary)] text-sm font-bold px-4 py-2 rounded border border-[var(--color-border)] flex items-center gap-2">
          <Save size={16} />
          CHANGES SAVE PER BROKER
        </div>
      </header>

      <div className="flex flex-col gap-4">
        <h3 className="text-lg font-bold text-[var(--color-text-primary)] border-b border-[var(--color-border)] pb-2">
          Operator Authentication
        </h3>
        <div className="panel p-5 flex flex-col gap-4">
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_auto_auto] gap-3 items-end">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-mono text-[var(--color-text-secondary)]">HITL AUTH TOKEN</span>
              <input
                type="password"
                value={operatorToken}
                onChange={(e) => setOperatorToken(e.target.value)}
                placeholder="Paste the token you used to open the control plane"
                className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-3 py-2 text-sm text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-accent)] font-mono"
              />
            </label>
            <button
              onClick={() => void handleSaveOperatorToken()}
              className="text-xs font-bold px-4 py-2 rounded bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent)]/80 transition-colors"
            >
              SAVE TOKEN
            </button>
            <button
              onClick={handleClearOperatorToken}
              className="text-xs font-bold px-4 py-2 rounded border border-[var(--color-border)] hover:bg-[var(--color-panel-hover)] transition-colors text-[var(--color-text-secondary)]"
            >
              CLEAR TOKEN
            </button>
          </div>
          <p className="text-xs font-mono text-[var(--color-text-secondary)] leading-relaxed">
            Protected routes use this token for manual trades, order approvals, broker credential storage, and connectivity checks.
          </p>
          {tokenStatus && (
            <div className="rounded border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-xs font-mono text-[var(--color-text-secondary)]">
              {tokenStatus}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <h3 className="text-lg font-bold text-[var(--color-text-primary)] border-b border-[var(--color-border)] pb-2 flex items-center gap-2">
            <Shield size={18} className="text-[var(--color-accent)]" />
            Broker Credentials
          </h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {brokers.map((broker) => {
            const isActiveBroker = broker.id === activeBrokerName;
            const hasBrokerOutage = isActiveBroker && brokerHealth?.available === false;
            const hasReconciliationMismatch = isActiveBroker && reconciliation?.matched === false;
            const isConnected = broker.status === 'connected' && !hasBrokerOutage;
            const isConfiguring = configuringBroker === broker.id;

            return (
              <div key={broker.id} className="panel p-5 flex flex-col gap-4">
                <div className="flex items-center justify-between border-b border-[var(--color-border)] pb-3">
                  <div className="flex items-center gap-3">
                    <div className={cn(
                      'w-8 h-8 rounded flex items-center justify-center',
                      isConnected ? 'bg-[var(--color-success)]/10 text-[var(--color-success)]' : 'bg-[var(--color-text-secondary)]/10 text-[var(--color-text-secondary)]',
                    )}>
                      {isConnected ? <Wifi size={16} /> : <WifiOff size={16} />}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-bold text-sm">{broker.name}</h3>
                        <span
                          className={cn(
                            'w-2 h-2 rounded-full',
                            isConnected ? 'bg-[var(--color-success)] shadow-[0_0_8px_var(--color-success)] animate-pulse' : 'bg-[var(--color-danger)]',
                          )}
                          title={isConnected ? 'Configured' : 'Not configured'}
                        />
                      </div>
                      <p className="text-[10px] font-mono text-[var(--color-text-secondary)]">{broker.type}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={cn(
                      'text-[10px] font-mono px-2 py-1 rounded border',
                      broker.env === 'LIVE'
                        ? 'bg-[var(--color-danger)]/10 text-[var(--color-danger)] border-[var(--color-danger)]/20'
                        : 'bg-[var(--color-warning)]/10 text-[var(--color-warning)] border-[var(--color-warning)]/20',
                    )}>
                      {broker.env}
                    </span>
                    <span className={cn(
                      'text-[10px] font-mono px-2 py-1 rounded border',
                      isConnected
                        ? 'bg-[var(--color-success)]/10 text-[var(--color-success)] border-[var(--color-success)]/20'
                        : hasBrokerOutage
                          ? 'bg-[var(--color-danger)]/10 text-[var(--color-danger)] border-[var(--color-danger)]/20'
                          : 'bg-[var(--color-text-secondary)]/10 text-[var(--color-text-secondary)] border-[var(--color-border)]',
                    )}>
                      {hasBrokerOutage ? 'OUTAGE' : broker.status.toUpperCase()}
                    </span>
                  </div>
                </div>

                {hasBrokerOutage && (
                  <div className="rounded border border-[var(--color-danger)]/25 bg-[var(--color-danger)]/5 px-3 py-2 text-xs font-mono text-[var(--color-text-secondary)]">
                    <div className="text-[var(--color-danger)]">Broker unavailable</div>
                    <div className="mt-1">
                      Failures: {brokerHealth?.consecutive_failures ?? 0}
                      {brokerHealth?.context ? ` · Context: ${brokerHealth.context}` : ''}
                    </div>
                    {brokerHealth?.last_error && <div className="mt-1 truncate">Last error: {brokerHealth.last_error}</div>}
                  </div>
                )}

                {hasReconciliationMismatch && (
                  <div className="rounded border border-[var(--color-warning)]/25 bg-[var(--color-warning)]/5 px-3 py-2 text-xs font-mono text-[var(--color-text-secondary)]">
                    <div className="text-[var(--color-warning)]">Portfolio reconciliation mismatch</div>
                    <div className="mt-1">
                      {typeof reconciliation?.cash_delta === 'number' ? `Cash Δ ${reconciliation.cash_delta}` : 'Cash unchanged'}
                      {typeof reconciliation?.portfolio_value_delta === 'number' ? ` · Equity Δ ${reconciliation.portfolio_value_delta}` : ''}
                    </div>
                    {!!Object.keys(reconciliation?.share_deltas ?? {}).length && (
                      <div className="mt-1">
                        Symbol drift: {Object.keys(reconciliation?.share_deltas ?? {}).join(', ')}
                      </div>
                    )}
                  </div>
                )}

                {isConfiguring ? (
                  <div className="flex flex-col gap-3 animate-in fade-in slide-in-from-top-2">
                    <div className="flex flex-col gap-1.5">
                      <label className="text-xs font-mono text-[var(--color-text-secondary)] flex items-center gap-1.5">
                        <Key size={12} /> API KEY
                      </label>
                      <input
                        type="password"
                        value={formValues.apiKey}
                        onChange={(e) => setFormValues({ ...formValues, apiKey: e.target.value })}
                        placeholder={isConnected ? '••••••••••••••••••••••••' : 'Enter API Key'}
                        className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-3 py-2 text-sm text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-accent)] font-mono"
                      />
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <label className="text-xs font-mono text-[var(--color-text-secondary)] flex items-center gap-1.5">
                        <Shield size={12} /> {broker.id === 'angel_one' ? 'PIN' : 'API SECRET'}
                      </label>
                      <input
                        type="password"
                        value={formValues.apiSecret}
                        onChange={(e) => setFormValues({ ...formValues, apiSecret: e.target.value })}
                        placeholder={isConnected ? '••••••••••••••••••••••••••••••••' : 'Enter API Secret'}
                        className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-3 py-2 text-sm text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-accent)] font-mono"
                      />
                    </div>

                    {broker.id === 'angel_one' && (
                      <>
                        <div className="flex flex-col gap-1.5">
                          <label className="text-xs font-mono text-[var(--color-text-secondary)] flex items-center gap-1.5">
                            <Server size={12} /> CLIENT CODE
                          </label>
                          <input
                            type="text"
                            value={formValues.clientCode}
                            onChange={(e) => setFormValues({ ...formValues, clientCode: e.target.value })}
                            placeholder="Enter Client Code"
                            className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-3 py-2 text-sm text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-accent)] font-mono"
                          />
                        </div>

                        <div className="flex flex-col gap-1.5">
                          <label className="text-xs font-mono text-[var(--color-text-secondary)] flex items-center gap-1.5">
                            <Key size={12} /> TOTP SECRET
                          </label>
                          <input
                            type="password"
                            value={formValues.totpSecret}
                            onChange={(e) => setFormValues({ ...formValues, totpSecret: e.target.value })}
                            placeholder="Enter TOTP Secret"
                            className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-3 py-2 text-sm text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-accent)] font-mono"
                          />
                        </div>
                      </>
                    )}

                    <div className="flex flex-col gap-1.5">
                      <label className="text-xs font-mono text-[var(--color-text-secondary)] flex items-center gap-1.5">
                        <Server size={12} /> ENVIRONMENT
                      </label>
                      <select
                        value={formValues.env}
                        onChange={(e) => setFormValues({ ...formValues, env: e.target.value })}
                        className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-3 py-2 text-sm text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-accent)] font-mono"
                      >
                        <option value="PAPER">PAPER</option>
                        <option value="LIVE">LIVE</option>
                      </select>
                    </div>

                    <div className="flex justify-end mt-2 gap-2">
                      <button
                        onClick={() => {
                          setConfiguringBroker(null);
                          setFormValues({ apiKey: '', apiSecret: '', clientCode: '', totpSecret: '', env: 'PAPER' });
                        }}
                        className="text-xs font-bold px-4 py-2 rounded hover:bg-[var(--color-panel-hover)] transition-colors text-[var(--color-text-secondary)]"
                      >
                        CANCEL
                      </button>
                      <button
                        onClick={() => void handleSaveBroker(broker.name)}
                        className="text-xs font-bold px-4 py-2 rounded bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent)]/80 transition-colors"
                      >
                        SAVE CONFIG
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-between mt-1 pt-2">
                    <button
                      onClick={() => setConfiguringBroker(broker.id)}
                      className="text-xs font-bold px-4 py-2 rounded border border-[var(--color-border)] hover:bg-[var(--color-panel-hover)] transition-colors flex items-center gap-2 text-[var(--color-text-secondary)]"
                    >
                      <Settings2 size={14} /> CONFIGURE
                    </button>
                    <div className={cn(
                      'text-xs font-bold px-4 py-2 rounded border',
                      isConnected
                        ? 'bg-[var(--color-success)]/10 text-[var(--color-success)] border-[var(--color-success)]/20'
                        : 'bg-[var(--color-panel-hover)] text-[var(--color-text-secondary)] border-[var(--color-border)]',
                    )}>
                      {isConnected ? 'CONFIG SAVED' : 'NOT CONFIGURED'}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
        </div>
      </div>

      <div className="panel p-5 flex flex-col gap-3">
        <h3 className="text-lg font-bold text-[var(--color-text-primary)]">Scope Note</h3>
        <p className="text-xs font-mono text-[var(--color-text-secondary)] leading-relaxed">
          This page intentionally exposes only supported settings behavior. Saved credentials are consumed by the
          control-plane execution path and connectivity checks. Generic connect toggles and market-data feed cards
          were removed because they were not backed by real server actions.
        </p>
      </div>
    </div>
  );
}
