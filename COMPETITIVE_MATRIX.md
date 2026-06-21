# COMPETITIVE MATRIX

## Systems Compared

| Dimension | new-trade (this system) | NautilusTrader | QuantConnect LEAN | TradingAgents | OpenBB |
|---|---|---|---|---|---|
| **Engine Language** | Python 3.12 | Rust core + Python bindings | C# core + Python bindings | Python (LangGraph) | Python (FastAPI + Pydantic) |
| **Architecture** | Event-driven, 11 agents, in-process bus | Event-driven, component-based, msg bus | Event-driven, modular framework | LLM multi-agent (LangGraph) | REST API + ODP platform |
| **Primary Purpose** | NSE paper trading | Multi-asset algo trading | Multi-asset algo trading | LLM trading research | Financial data platform |
| **Backtesting** | Yes (BacktestEngine + synthetic) | Yes (deterministic, nano-second) | Yes (industrial grade) | No (research only) | No (data platform) |
| **Live Trading** | Gated (not enabled) | Yes (production grade) | Yes (300k+ live algos) | No (research only) | No (data platform) |
| **Asset Classes** | NSE equities | Multi-asset | Multi-asset | US equities | Multi-asset |
| **Broker Connectors** | 4 stubs + paper simulator | 30+ production adapters | 20+ production brokers | 0 (data only) | 50+ data providers |
| **Languages** | Python only | Python + Rust | C# + Python | Python only | Python + REST |
| **Risk Engine** | 8 custom modules | RiskEngine (state machine: ACTIVE/REDUCING/HALTED) | Risk management framework | LLM-based risk manager | N/A (data platform) |
| **Kill Switch** | Custom (drawdown + daily loss) | TradingState (ACTIVE/REDUCING/HALTED) | Algorithmic trading controls | LLM-based | N/A |
| **Order Types** | MARKET, LIMIT, SL, SL-M, MIS, CNC, CO | Full: IOC, FOK, GTC, GTD, DAY, OCO, OUO, OTO, icebergs, post-only, reduce-only | Full: all order types + contingent orders | Simulated only | N/A |
| **Position Sizing** | Kelly, ATR, HRP | PositionSizer component | Framework models | LLM-based | N/A |
| **Portfolio Optimization** | Ledoit-Wolf, 4 regimes | Built-in | Risk parity, mean-variance, etc. | None | N/A |
| **Event Store** | SQLite / Postgres / Kafka | Redis-backed | SQLite / custom | SQLite (checkpoints) | Not applicable |
| **Metrics/Observability** | Prometheus text + SQLite | Prometheus + logging | Console + file | Logging | Built-in |
| **Market Data** | Yahoo (free) + backtest provider | All major + custom adapters | 400TB+ licensed data | LLM processed | 50+ providers unified |
| **Kill Switch Persistence** | File-based JSON | None (state machine) | None | N/A | N/A |
| **SL/TP** | Manual (trailing) | Native | Native | LLM-based | N/A |
| **TWAP/Iceberg** | Custom chunked TWAP | Native (icebergs, TWAP, VWAP) | Not built-in | None | N/A |
| **Reconciliation** | Broker vs local drift | Built-in position reconciliation | Built-in | None | N/A |
| **Duplicate Order Protection** | Partial (broker-only) | Native (idempotency keys) | Native | N/A | N/A |
| **Circuit Breakers** | None | TradingState HALTED | Framework | None | N/A |
| **Latency Budget** | None documented | Sub-microsecond | Milliseconds | Seconds (LLM) | N/A |
| **Fail-Fast Policy** | Graceful (logs + continues) | Yes (panic on invalid data) | Yes | None | N/A |
| **Unit Tests** | ~50 test files | Extensive (12k+ tests) | 12,000+ | Minimal | Extensive |
| **Test Coverage** | ~80% (target) | >80% | >80% | Low | High |
| **Documentation** | Architecture + operations + runbook | Comprehensive (API + concepts + tutorials) | Comprehensive | README + paper | Comprehensive |
| **Headless Mode** | Yes (CLI + HTTP) | Yes | Yes | Yes (CLI) | Yes (REST) |
| **Free Tier** | Yes (entirely free) | Yes (Apache 2.0) | Yes (Apache 2.0) | Yes (CC BY-NC-SA) | Yes (community edition) |
| **License** | Proprietary | LGPL 2.1+ | Apache 2.0 | CC BY-NC-SA 4.0 | MIT (core) |
| **Community Stars** | Private | 5k+ GitHub | 16k+ GitHub | 49k+ GitHub | 67k+ GitHub |
| **Data Backtesting Quality** | Synthetic + historical CSV | Tick/bar level, deterministic | Point-in-time, 400TB+ tick data | None | Historical via providers |
| **Authentication** | Bearer token (optional) | API keys | JWT + cloud auth | None | API keys + SSO |
| **Margin Model** | None (exposure only) | Built-in margin calculators | Full (cash, margin, options) | None | N/A |
| **Tax Lot Accounting** | FIFO (Kelly only) | FIFO/LIFO configurable | FIFO | None | N/A |
| **Trade Journal Export** | None | Parquet export | CSV/JSON export | JSON logs | REST API |
| **Market Classification** | 4 regimes (trending_up/down, mean_reverting, high_vol) | N/A (strategy-level) | N/A (strategy-level) | LLM based | N/A |
| **Auto-Mutation** | ReflectionEngine (gated) | None | None | None | N/A |

## Key Gaps vs Leaders

### vs NautilusTrader
1. **Engine performance**: Python-only vs Rust-native. Tick-to-order latency difference is ~100x.
2. **Order type support**: Missing IOC, FOK, GTC, GTD, OCO, OUO, OTO, contingent orders.
3. **Asset class support**: NSE equities only vs multi-asset.
4. **Fail-fast policy**: new-trade logs and continues; NautilusTrader panics on invalid data — prevents silent corruption.
5. **Community & maturity**: NautilusTrader has 5k+ stars, 200+ releases, professional team.

### vs QuantConnect LEAN
1. **Backtesting fidelity**: LEAN has point-in-time data with survivorship bias handling; new-trade uses synthetic ticks.
2. **Broker integration**: LEAN has 20+ production adapters; new-trade has 4 stubs.
3. **Scale**: LEAN processes $45B/month notional volume across 300k+ live algorithms.
4. **Test suite**: LEAN has 12,000+ unit tests; new-trade has ~50 test files.
5. **Data catalog**: LEAN has 400TB+ of historical data from 40+ vendors.

### vs TradingAgents
1. **Different paradigm**: TradingAgents is LLM-first (LangGraph) with agentic debate; new-trade is numeric signal-based.
2. **No backtesting**: TradingAgents has no backtest engine — research only.
3. **No live trading**: TradingAgents simulates fills only.
4. **Complementary**: A merge could use TradingAgents for regime classification and new-trade for execution.

### vs OpenBB
1. **Not comparable**: OpenBB is a data platform, not a trading engine.
2. **Data quality**: OpenBB has 50+ data providers with unified schema; new-trade has Yahoo + backtest provider.
3. **Potential integration**: new-trade could use OpenBB as a data source for live market data.

## Summary

new-trade is **not competitive** with NautilusTrader or QuantConnect LEAN as a general-purpose algo trading platform. However, it is:
- **Competitive as a specialized NSE paper trading system** — no other open-source system specifically targets NSE with Indian broker connectors (Kite, Angel, Groww).
- **Architecturally sound** — the event-sourced design and risk infrastructure would scale to live trading with proper hardening.
- **Differentiated by the multi-agent approach** — the 11-agent architecture with dedicated risk, reconciliation, and reflection agents is more structured than the monolithic strategy pattern used by NautilusTrader and LEAN.
- **Missing critical features** for live trading: margin models, tax lot accounting, circuit breakers, market data validation, and proper order book handling.
