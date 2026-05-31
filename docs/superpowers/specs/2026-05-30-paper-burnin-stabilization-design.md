# Paper Burn-In Stabilization Design

## Goal

Prepare the trading system for a monitored 24-hour paper-trading burn-in using Angel live
WebSocket market data while guaranteeing that order execution remains simulated.

## Scope

This stabilization slice restores strategy import compatibility, clears CI failures, adds a
persistent Angel symbol-token cache, aligns dashboard build and serving paths, and launches a
paper-only burn-in with reconciliation reporting every 30 minutes.

## Strategy Compatibility

Strategy implementations remain in `src/strategies`. `src.agents.strategy_gen` remains a stable
compatibility surface by re-exporting the moved strategy classes. This preserves older tests and
external imports without duplicating strategy logic.

## Angel Symbol Cache

`AngelSymbolIndex` persists the Angel master contract under `state/angel_symbols.json`. It loads a
fresh local cache first, refreshes from Angel only when the cache is missing or expired, and keeps
using stale cached data if refresh fails. Token resolution uses an in-memory lookup keyed by
exchange and trading symbol or name.

The existing Angel client delegates symbol-map loading to this index. WebSocket subscriptions still
accept explicit tokens so startup can bypass refresh when a deployment already has a known token.

## Dashboard Deployment

The React build output is standardized on `dashboard/dist`. FastAPI serves that directory. Docker
continues copying `dashboard/dist` into the image. This removes the current mismatch between the
frontend builder and the backend static path.

## CI Quality Gates

CI remains authoritative:

1. `ruff check src tests`
2. `mypy src`
3. `pytest tests`
4. `npm run build`

Formatting changes are mechanical and scoped. Real Ruff and mypy findings are fixed directly.

## Paper Burn-In

The burn-in launcher:

- activates `.venv`
- clears Kite live broker credentials
- enables Angel live WebSocket market data
- runs the Python application in paper mode
- exposes `/health` and `/metrics`
- runs reconciliation every 30 minutes
- writes logs and reconciliation snapshots below `state/burnin/`
- records the process ID for monitoring and stop operations

Reconciliation validates local paper order and position state only. It does not call a live broker.

## Monitoring

A heartbeat wakes this thread every 30 minutes for 24 hours. Every check reports process liveness,
health endpoint status, metrics reachability, latest reconciliation result, order/fill counts, and
recent errors.

## Safety

The launcher clears Kite credentials before startup. The burn-in must not submit live orders.
Angel credentials are used only for read-only market-data authentication.
