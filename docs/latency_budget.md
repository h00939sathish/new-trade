# Latency Budget

## SLAs (Service Level Agreements)

All values are P99 (99th percentile) unless noted.

| Path | Paper Target | Live Target | Measurement Method |
|---|---|---|---|
| Event bus delivery (subscribe → receive) | <10ms | <5ms | `latency_tracer` in `src/monitoring/latency_tracer.py` |
| Order-to-fill (order → fill event) | <500ms | <100ms | Fill event timestamp − Order event timestamp |
| Kill-switch trigger-to-flatten | <1s | <500ms | Trigger timestamp − last order cancel timestamp |
| Reconciliation full scan | <5s | <3s | `_run_reconciliation` wall-clock time |
| Metrics flush to store | <1s | <500ms | `flush_interval` in `MetricsCollector` |
| Strategy evaluation (per tick) | <50ms | <20ms | `latency_tracer` correlation ID |
| Risk check (per signal) | <100ms | <50ms | `latency_tracer` correlation ID |

## Critical Path: Tick → Order

```
Market data arrival (TICK event)
  ├─ Event bus: <10ms
  ├─ MarketIntelAgent: <5ms
  ├─ StrategyGenAgent evaluation: <50ms
  │   └─ Signal event emitted
  ├─ RiskManagementAgent validation: <100ms
  │   └─ RiskCheckEvent emitted
  ├─ ExecutionAgent submit: <10ms
  │   └─ Order placed
  └─ Fill simulated (paper) / Broker ack (live): <500ms / <100ms
```

**Total paper:** ~675ms P99
**Total live:** ~185ms P99 (excludes broker network RTT)

## Bottlenecks

1. **StrategyGenAgent**: Iterates all registered strategies sequentially per tick. With 5 active strategies, this is the largest single contributor.
2. **RiskManagementAgent**: 9 pre-trade checks run sequentially per signal.
3. **SQLite persistence**: WAL mode mitigates but write contention can spike latency on flush.

## Profiling

Run the system with `TRA_LOG_LEVEL=DEBUG` and monitor the `latency_tracer` metrics:

```bash
# Enable latency tracing
export TRA_LATENCY_TRACING_ENABLED=true
python -m src.main

# Check P99 latencies
curl http://localhost:8080/metrics | grep latency
```
