# Phase 3: Performance Audit

---

## 1. Event Loop Bottlenecks

### Current Architecture
- Async event loop with 5 priority queues
- Single-threaded Python asyncio (GIL-bound)
- Callback-heavy: every tick traverses: WebSocket → market_intel → on_tick → strategy_gen → risk_mgmt → execution → portfolio_opt → metrics

### Measured Hot Path
```
Tick arrives
  → AngelWebSocket._dispatch_message (thread-safe, uses call_soon_threadsafe)
  → market_intel._on_tick (Python callback)
  → publish(TICK) to event bus
    → strategy_gen.on_event (signal generation)
      → _compute_indicators (NumPy, ~0.5-2ms per indicator per instrument)
      → _publish_signals (dictionary merging, fast)
    → risk_mgmt.on_event (SIGNAL → risk checks)
      → VaR computation (O(n) on price_history dequeue, n=min 20)
      → margin check (O(1))
      → kill switch check (O(1))
    → execution.on_event (RISK_CHECK → order)
      → paper fill simulation (O(1), ~0.1ms)
    → portfolio_opt.on_event (FILL → position tracking)
      → position update (O(1))
      → metrics update (O(1))
```

### Issues
1. **[MEDIUM] Sequential Processing**: All agents process each event sequentially on the same event loop. With 14 strategies computing indicators per tick, total per-tick latency can exceed 50ms. At 1 tick/second (typical NSE polling), this is acceptable. At WebSocket speed (10+ ticks/second), latency accumulates.
2. **[HIGH] Synchronous numpy in asyncio**: `_compute_indicators` uses numpy synchronously — blocks the event loop. StrategyGen's `_compute_and_store` (strategy_gen.py:430-480) calls numpy rolling window ops which are CPU-bound and GIL-locked.
3. **[LOW] No Tick Batching**: Ticks processed individually. Batching 5-10 ticks per cycle would reduce per-tick overhead by ~60%.

## 2. Memory Profile

### Current Consumption (estimated)
| Component | Memory | Growth Rate |
|-----------|--------|-------------|
| Price history (deque, 100 per instrument, 4 symbols) | ~16 KB | Negligible |
| Strategy state (rolling windows, 20-100 period) | ~50 KB | Negligible |
| Event bus queues (5 queues, max 500+500+500+500+200) | ~50 MB at max | Linear with backpressure |
| Metrics history (counter dicts, latency deque 1000) | ~50 KB | Bounded |
| SQLite connections (order_state.db, events.db) | ~2 MB | Constant |
| Angel symbol map (5000+ instruments cached) | ~5 MB | Constant |

### Issues
1. **[HIGH] Event Queue Memory Blow-up**: Backpressure threshold at 500 events. At peak volatility with 100+ events/second (14 strategies × 4 symbols × 2 events/tick), queues can fill in ~2 seconds. Backpressure drops events but memory still spikes to 50MB.
2. **[MEDIUM] Angel Symbol Map Memory**: `state/angel_symbols.json` ~3-5MB. Loaded into memory as Python dict with 5000+ entries — OK for current scale but 500+ symbols would stress it.

## 3. I/O Patterns

### Database Writes
- `order_state.db`: SQLite for TWAP tracking — write on every order state change (~0.5ms per write)
- `trading_events.db`: MetricsStore — flush every 10s (batched)
- `kill_switch.state`: JSON file write on state change (~1ms)

### Issues
1. **[MEDIUM] SQLite Lock Contention**: `order_state.db` and `trading_events.db` are separate databases — no contention between them. But order_state.db write + metrics store write simultaneously could cause filesystem contention on HDD.
2. **[LOW] JSON File Write Inefficiency**: `kill_switch.state` written via `json.dump` — fine for infrequent writes (<1/sec).

## 4. Broker API Rate Limits

| Broker | Endpoint | Rate Limit | Current Usage |
|--------|----------|------------|---------------|
| Angel | Order placement | 10 OPS (SEBI) | Paper mode: 0; Live: ~2-5 OPS |
| Angel | LTP quote | 50 req/min (estimated) | 1 req/sec/poll = 60/min — exceeds |
| Angel | Historical data | 10 req/min (estimated) | ~4 req per backtest init |
| Kite | All APIs | 10 OPS (order), 250 req/min (REST) | Polling at 1 Hz = 60/min |
| Yahoo | Chart API | Unauthenticated, ~200/hr | ~10 req per backtest |

### Issues
1. **[HIGH] Angel LTP Polling Exceeds Rate Limit**: `_poll_loop` polls at 1 Hz for each instrument. With 4 instruments, that's 4 req/sec = 240 req/min. Angel likely blocks at 50-100 req/min.
2. **[HIGH] No Kite Order Rate Limiting**: No throttle on `place_order`. At 5 orders/sec could exceed 10 OPS limit, triggering exchange-level penalties.
3. **[MEDIUM] Yahoo Finance Throttling**: Backtest data fetches 4 symbols × 7 days = 28 Yahoo API calls. For longer periods (60 days), could exceed Yahoo's unauthenticated limit.

## 5. Startup Performance

### Measured Startup Sequence (from Phase 0B)
| Step | Duration | Cumulative |
|------|----------|------------|
| Config loading + secrets | ~50ms | 50ms |
| Event bus init | ~10ms | 60ms |
| Agent creation (9 agents) | ~200ms | 260ms |
| Agent start + subscriptions | ~50ms | 310ms |
| Angel client connect + login | ~800ms | 1110ms |
| Angel symbol index load | ~1200ms | 2310ms |
| Kite connect (placeholder) | ~50ms | 2360ms |
| Market data provider start | ~100ms | 2460ms |
| Strategy config load | ~10ms | 2470ms |
| **Total startup time** | | **~2.5 seconds** |

### Issues
1. **[MEDIUM]** Angel symbol index download from GitHub (OpenAPIScripMaster.json) can take 3-10 seconds on slow connections — blocks startup
2. **[LOW]** No lazy loading — all agents and connectors initialize at startup

## 6. Scalability Limits

| Dimension | Current Limit | Bottleneck |
|-----------|--------------|------------|
| Instruments | ~10 before event loop lag | Synchronous numpy + sequential agent processing |
| Strategies | 14 (3 active) | Strategy count doesn't affect perf linearly (all compute on every tick regardless of activity) |
| Event rate | ~50 events/sec before backpressure drops | Single-threaded event loop |
| Concurrent orders | ~5/sec | 10 OPS exchange limit, but no client-side throttle |
| Backtest duration | ~100K ticks before memory concerns | InMemoryEventStore holds all events |

## 7. Recommendations

1. **[HIGH] Offload numpy to ThreadPoolExecutor**: `_compute_indicators` and `_compute_and_store` should use `loop.run_in_executor(None, compute_fn)` to avoid blocking the event loop.
2. **[HIGH] Add Order Rate Limiter**: Implement token bucket algorithm for order placement (max 8 OPS for safety margin below 10 OPS limit).
3. **[MEDIUM] Batch Tick Processing**: Collect ticks for 200ms, process as batch. Reduces overhead by ~60%.
4. **[MEDIUM] Reduce Angel LTP Poll Rate**: 1 Hz is excessive. 5-second polling is sufficient for NSE cash markets.
5. **[LOW] Add Connection Pooling**: Reuse httpx clients (already done in Angel, not yet in Kite).
6. **[LOW] Lazy Load Symbol Index**: Don't load 5000 symbols on startup — load on first `resolve_token` call.
