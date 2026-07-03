# OANDA Forex and Gold Paper-Trading Design

**Date:** 2026-07-03  
**Status:** Approved for implementation planning

## Objective

Extend the existing event-sourced paper-trading system to support `XAU_USD`
(spot gold) and `EUR_USD` through an OANDA practice account. Signals use
completed one-minute candles with fifteen-minute trend confirmation. The
integration remains paper-only and does not change existing NSE behavior.

The initial virtual account uses USD 10,000 equity, risks at most 0.5% per
trade, limits combined open risk to 1%, and activates the daily kill switch at
a 2% loss.

## Scope

### Included

- OANDA v20 practice authentication and account discovery.
- Historical candle backfill for `M1` data.
- Live bid/ask price streaming for `XAU_USD` and `EUR_USD`.
- Deterministic `M15` aggregation from completed `M1` candles.
- Instrument metadata discovery, including price precision, trade-unit
  precision, minimum trade size, pip location, and market status.
- Instrument-specific strategy profiles.
- Risk-based unit sizing in a USD-denominated account.
- OANDA practice order submission and transaction/fill reconciliation.
- Parallel expected-fill simulation and execution-quality measurement.
- Internal simulated execution as an explicit fallback mode.
- Historical walk-forward validation and a 30-trading-day paper gate.

### Excluded

- Live-money execution.
- MCX gold futures or any instrument other than `XAU_USD` and `EUR_USD`.
- DRL strategy promotion.
- Automatic strategy mutation.
- Multiple simultaneous positions in one instrument.
- Position pyramiding.
- Regulatory readiness or live-broker compliance work.

## Architecture

OANDA-specific behavior is isolated behind market-data and broker adapters.
The existing event bus, agents, strategy interface, risk pipeline, portfolio
tracking, and monitoring remain the system spine.

```text
OANDA Practice
  |-- REST: instruments, M1 backfill, account state
  |-- pricing stream: bid/ask and heartbeat
  `-- orders/transactions: practice execution and fills
             |
             v
OANDA adapters
             |
             v
Existing event bus and agents
  |-- MarketIntelAgent
  |-- M1 strategy evaluation
  |-- M15 trend confirmation
  |-- RiskManagementAgent
  `-- ExecutionAgent
             |
       +-----+----------------+
       |                      |
       v                      v
OANDA practice orders   Expected-fill simulator
       |                      |
       +----------+-----------+
                  v
       Reconciliation and metrics
```

Provider-neutral instrument profiles define symbols, asset class, account and
quote currencies, session calendar, precision, minimum quantity, spread
limits, cost model, and strategy configuration. Existing NSE profiles and
connectors continue to operate unchanged.

## Configuration

New settings use the existing `TRA_` environment-variable convention.
Credentials and account identifiers are never committed.

Required settings:

- OANDA environment: `practice` only for this feature.
- OANDA account ID and API token.
- Enabled instruments: `XAU_USD,EUR_USD`.
- Execution mode: `oanda_practice` or `internal_simulation`.
- Starting paper equity: `10000 USD` for internal simulation.
- Risk per trade: `0.005`.
- Maximum combined open risk: `0.01`.
- Daily loss limit: `0.02`.

Startup must reject live OANDA endpoints and must fail closed when required
practice credentials or instrument metadata are unavailable.

## Market-Data Flow

1. On startup, query the OANDA account instruments endpoint and validate that
   both configured instruments are available and tradeable for the account.
2. Backfill enough completed `M1` candles to warm every active strategy and
   the `M15` trend filters.
3. Subscribe to the bid/ask pricing stream and monitor its heartbeat.
4. Poll or fetch newly completed `M1` candles using the timestamp of the last
   accepted candle as the cursor.
5. Reject duplicate, incomplete, out-of-order, or malformed candles.
6. Detect sequence gaps and suspend new entries for that instrument.
7. Backfill the missing range, rebuild affected `M15` bars, and resume only
   after continuity is restored.
8. Aggregate `M15` candles from UTC-aligned groups of fifteen accepted `M1`
   candles. Only complete groups are emitted.

The pricing stream supplies executable bid/ask prices and spread metrics. The
candle stream supplies strategy inputs. OANDA candle `volume` is quote-update
count rather than centralized traded volume and must not be treated as traded
volume.

## Strategy Profiles

The system reuses existing strategy classes but selects and parameterizes them
per instrument. Strategy weights are not shared across instruments.

### `XAU_USD`

- One-minute time-series momentum.
- One-minute volatility breakout.
- Fifteen-minute EMA and ADX trend confirmation.
- ATR initial stop and trailing exit.
- Maximum-spread and volatility-spike entry filters.
- Mean reversion disabled for the initial baseline.

### `EUR_USD`

- One-minute time-series momentum.
- Conservative one-minute sideways mean reversion.
- Lower-weight one-minute volatility breakout.
- Fifteen-minute EMA and ADX confirmation.
- ATR initial stop and trailing exit.
- Maximum-spread and liquid-session entry filters.

VWAP is disabled for both instruments because the source does not provide
centralized traded volume. NSE opening-range logic, NSE transaction costs, and
equity-specific stat-arbitrage pairs do not apply. DRL stays disabled until the
deterministic baseline passes the promotion gate.

## Signal Confirmation

A one-minute strategy may create a candidate signal only from a completed
`M1` candle. A candidate becomes an executable signal only when the latest
completed `M15` regime permits its direction. A stale or not-yet-warmed `M15`
state rejects the candidate rather than allowing an unconfirmed trade.

The decision event records:

- instrument and strategy;
- source `M1` candle timestamp;
- confirming `M15` candle timestamp;
- signal direction and confidence;
- ATR and proposed stop distance;
- observed bid, ask, and spread;
- rejection reason when blocked.

## Risk and Position Sizing

For each proposed trade:

```text
risk_budget_usd = current_equity_usd * 0.005
risk_per_unit_usd = abs(entry_price - stop_price) * quote_to_usd_factor
raw_units = risk_budget_usd / risk_per_unit_usd
```

Units are rounded down to the instrument's OANDA trade-unit precision and
must satisfy its minimum trade size. A trade is rejected when conversion data
is stale, the stop distance is invalid, the rounded size is zero, or combined
open risk would exceed 1% of current equity.

Additional controls:

- Maximum one open position per instrument.
- No pyramiding.
- A 2% realized-plus-unrealized daily loss activates the kill switch.
- The kill switch blocks new entries and permits position-reducing exits.
- Spread and stale-price filters run before order submission.
- Risk limits are calculated from current equity, not initial equity.

## Hybrid Execution

OANDA practice execution is authoritative when execution mode is
`oanda_practice`.

Before submission, the internal simulator records an expected fill using the
current executable side of the bid/ask quote plus configured slippage. The
execution adapter submits an idempotent client order ID to OANDA, persists the
request, and consumes the resulting transaction stream or REST response. The
actual practice fill updates positions and PnL; the expected fill is retained
only for execution-quality comparison.

The comparison records:

- expected and actual fill prices;
- spread at decision time;
- slippage in price units, pips, and basis points;
- decision-to-fill latency;
- rejection or cancellation reason.

Internal simulation is a separately selected fallback mode. The system must
not switch execution modes while any order is unresolved. If OANDA becomes
unavailable after submission, entries pause and reconciliation resolves the
order before any mode change. This prevents duplicate or conflicting
positions.

## Failure Handling

- **Pricing heartbeat lost:** mark prices stale and block new entries.
- **Candle gap:** block the affected instrument, backfill, then resume.
- **REST rate limit:** honor server guidance and use bounded exponential
  backoff with jitter.
- **Authentication failure:** fail startup or stop the adapter; never fall
  through to a live endpoint.
- **Order timeout:** mark the order unresolved and reconcile by client order
  ID before retrying.
- **Transaction-stream disconnect:** reconnect from the last known transaction
  ID and reconcile account state.
- **Instrument halted or closed:** reject entries and continue monitoring
  existing positions.
- **Metadata change:** refresh precision and margin metadata before accepting
  another order.
- **Reconciliation mismatch:** activate an execution halt for the affected
  instrument until resolved.

All retries are bounded. Failures emit structured events and metrics without
silently fabricating market data or fills.

## Persistence and Observability

Persist provider request IDs, OANDA transaction IDs, client order IDs, source
candle timestamps, expected fills, actual fills, and reconciliation outcomes.
Secrets must never appear in events or logs.

Metrics are labeled by instrument and strategy and include:

- stream health and reconnect count;
- candle lag, rejected candles, and gap count;
- bid/ask spread and stale-price duration;
- candidate, confirmed, and rejected signal counts;
- current and combined risk;
- expected-versus-actual slippage;
- realized and unrealized PnL;
- Sharpe, drawdown, win rate, and completed trades;
- unresolved orders and reconciliation mismatches.

## Testing

### Unit Tests

- OANDA response parsing and error mapping.
- Instrument metadata and decimal precision handling.
- Duplicate, incomplete, out-of-order, and missing candle behavior.
- UTC `M1` to `M15` aggregation.
- Directional trend confirmation and warm-up rejection.
- USD risk sizing for both instruments.
- Spread, stale-price, combined-risk, and daily-loss gates.
- Expected-fill calculation and execution-quality metrics.
- Idempotent client order IDs and unresolved-order handling.

### Integration Tests

- Recorded OANDA responses drive startup, backfill, and streaming without
  external network access.
- Disconnect and reconnect recover candles and transactions from cursors.
- Practice-order lifecycle maps correctly into existing order and fill events.
- OANDA and internal execution modes cannot overlap.
- Existing NSE tests continue to pass unchanged.

### Validation

Run historical walk-forward tests independently for each instrument and the
combined portfolio. Include spread and slippage sensitivity rather than
testing only midpoint OHLC data. After historical checks pass, run OANDA
practice trading for 30 trading days.

## Promotion Gate

The paper run passes only when all system-level conditions hold:

- At least 30 trading days completed.
- Net annualized Sharpe ratio at least 0.8.
- Maximum drawdown no greater than 8%.
- At least 100 completed trades across the enabled portfolio.
- No unresolved order or position reconciliation mismatch.
- No risk-limit violation.
- No execution-mode overlap or duplicate order.

Report the same metrics separately for `XAU_USD`, `EUR_USD`, each strategy,
and the combined portfolio. An instrument that fails its individual quality
gate is disabled without invalidating a passing instrument. Passing this gate
authorizes evaluation of the next paper phase only; it does not enable live
trading.

