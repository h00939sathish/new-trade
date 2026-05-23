# Changelog

## [Unreleased]

### 2026-05-23 — Phase 1 Build: Foundation
#### Added
- `plan.md` — Master architectural plan with 7-agent design, research findings, build-vs-buy decisions, MVP roadmap
- `init.md` — Project initialization overview, conventions, and setup instructions
- `CHANGELOG.md` — Change tracking file
- `pyproject.toml` — Python project config with deps (pydantic, asyncpg, aiokafka, httpx, etc.)
- `docker-compose.yml` — Kafka, Schema Registry, Redis, TimescaleDB for local dev
- `.env.example` — Environment template with TRA_ prefix
- `Makefile` — Dev commands (install, lint, test, run-*)

#### Core Schemas (`src/schemas/`)
- `Event` base class with 11 event types (Tick, OHLCV, Signal, Order, Fill, RiskCheck, Portfolio, System)
- Strongly-typed Pydantic models for all events
- Factory methods for easy event creation

#### Central Event Store (`src/event_store/`)
- `EventStore` abstract base class with async interface
- `InMemoryEventStore` — for testing
- `SqliteEventStore` — for local dev (WAL mode, indexed)
- `PostgresEventStore` — for production (TimescaleDB hypertable)
- `KafkaEventStore` — for production event bus
- Factory function for config-driven store creation

#### Agent Framework (`src/agents/`)
- `BaseAgent` — abstract agent class with lifecycle (start/stop), event bus subscription, health checks
- `MarketIntelAgent` — market data ingestion (ticks, OHLCV), builder pattern
- `StrategyGenAgent` — signal generation via pluggable strategies (Momentum, MeanReversion built-in)
- `RiskManagementAgent` — pre-trade signal/order validation, max position, drawdown, leverage checks
- `ExecutionAgent` — paper trading with simulated fills, order lifecycle management

#### Kite/Zerodha Connector (`src/connectors/kite/`)
- `KiteClient` — API wrapper with graceful fallback (paper mode when unconfigured)
- `KiteMarketDataProvider` — async polling for tick/OHLCV data
- `KiteBroker` — order placement, modification, cancellation

#### Tests
- 32 passing tests (100% pass rate)
- Event store tests: append, read, replay, batch, streams, delete, health
- Schema tests: all event types serialization roundtrip
- Agent tests: lifecycle, tick/OHLCV ingestion, strategy evaluation, risk validation, order placement

#### Scripts
- `scripts/run_agent.py` — Run individual agents or all agents
- `scripts/replay_events.py` — Replay events from store with stream/date filtering

#### Architecture Decisions
- Flat config with `TRA_` prefix to avoid environment variable collisions
- SQLite as default event store for zero-dependency local dev
- Event sourcing for full replayability
- Paper trading built into execution agent by default
- Strategy agent uses pluggable strategy pattern
- Risk validation as separate gate agent (not embedded in execution)

#### Research Completed
- All 6 research areas completed (engines, AI frameworks, infra, ML stack, strategies, architecture)
- Graphify installed and configured for codebase knowledge graph

---

*Format based on [Keep a Changelog](https://keepachangelog.com/)*
