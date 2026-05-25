import { Activity, LineChart, PlugZap, Settings, Signal, TerminalSquare } from 'lucide-react';
import { cn } from '../lib/utils';

interface SidebarProps {
  currentTab: string;
  setCurrentTab: (tab: string) => void;
  systemStatus?: string;
}

export function Sidebar({ currentTab, setCurrentTab, systemStatus = 'ONLINE' }: SidebarProps) {
  const isHalted = systemStatus === 'HALTED';
  const isDegraded = systemStatus === 'DEGRADED';
  const statusClassName = isHalted
    ? 'text-[var(--color-danger)]'
    : isDegraded
      ? 'text-[var(--color-warning)]'
      : 'text-[var(--color-success)]';
  const dotClassName = isHalted
    ? 'bg-[var(--color-danger)]'
    : isDegraded
      ? 'bg-[var(--color-warning)]'
      : 'bg-[var(--color-success)]';

  const navItems = [
    { id: 'dashboard', label: 'Pro Alpha Terminal', icon: TerminalSquare },
    { id: 'live-paper', label: 'Live Paper Trade', icon: Activity },
    { id: 'live-money', label: 'Live Money Trade', icon: Activity },
    { id: 'backtest', label: 'Backtest Engine', icon: LineChart },
    { id: 'connectivity', label: 'Broker Connectivity', icon: PlugZap },
    { id: 'broker', label: 'Broker Status', icon: Signal },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  return (
    <div className="w-64 border-r border-[var(--color-border)] bg-[var(--color-panel)] flex flex-col">
      <div className="p-6 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-[var(--color-accent)] flex items-center justify-center font-bold text-white">
            A
          </div>
          <div>
            <h1 className="font-bold text-sm tracking-wider">ALPHA SYSTEM</h1>
            <p className="text-[10px] text-[var(--color-text-secondary)] font-mono">v2.4.1 LIVE</p>
          </div>
        </div>
      </div>
      
      <nav className="flex-1 p-4 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setCurrentTab(item.id)}
              className={cn(
                "w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors",
                isActive 
                  ? "bg-[var(--color-accent)]/10 text-[var(--color-accent)] font-medium" 
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text-primary)]"
              )}
            >
              <Icon size={18} className={isActive ? "text-[var(--color-accent)]" : "opacity-70"} />
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="p-4 border-t border-[var(--color-border)]">
        <div className="flex items-center justify-between text-xs font-mono text-[var(--color-text-secondary)]">
          <span>STATUS</span>
          <span className={cn("flex items-center gap-1.5", statusClassName)}>
            <span className={cn(
              "w-2 h-2 rounded-full animate-pulse",
              dotClassName
            )}></span>
            {systemStatus}
          </span>
        </div>
      </div>
    </div>
  );
}
