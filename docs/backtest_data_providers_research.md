# Research: Free Backtest Data Providers for NSE (2026)

Date: 2026-06-06
Purpose: Identify the best free data provider for backtesting the trading
system's 3 active strategies (momentum, sideways_reversion, vwap_reversion)
on NSE stocks at 1-minute granularity over 30+ days.

## Hard requirement: 1-minute intraday, 30+ days, NSE

Most "free" market-data providers offer daily or weekly granularity
freely. 1-minute intraday data is a tier above that. Few providers give
it away for free for NSE.

## Provider comparison

| Provider | 1-min free? | 30-day free? | Auth | Rate limits | Verdict |
|---|---|---|---|---|---|
| **Upstox** | ✅ 1m available | ⚠️ only last month | OAuth 2.0 | 50/sec, 500/min, 2000/30min | **TIER 1 — best if you have account** |
| **Angel One** | ✅ via SmartConnect | ✅ depends on tier | API key + TOTP | 1 req/sec historical | **TIER 1 — already wired** |
| **Zerodha Kite** | ❌ intraday raw not via Kite Connect | ❌ | API key + token | 3 req/sec | NOT USEFUL for 1m backtest |
| **Yahoo Finance** | ✅ 1m, 7-day only | ❌ 7 days max | None | Unofficial | **TIER 2 — already wired as fallback** |
| **NSE India** (nse.co.in) | ✅ bhavcopy daily | ❌ 1m only via paid feeds | None | Unstable | NOT USEFUL for 1m |
| **Ninjascaler / AlgoTest** | ✅ EOD | ❌ | Login | Limited | NOT USEFUL for 1m |
| **Alpha Vantage** | ❌ intraday 5+ min | ⚠️ 5 calls/min free | API key | 5 calls/min, 500/day | NOT USEFUL for 1m |
| **Polygon.io** | ✅ 1m | ⚠️ 2 years free tier | API key | 5 calls/min free | TIER 2 if NSE supported (it's not — Polygon is US-only) |
| **Tradier / TD Ameritrade** | ✅ 1m | depends on tier | OAuth | varies | NOT USEFUL (US-only) |

## The actual constraint

For NSE 1-minute data, the only two providers that have it for free
are:

1. **Yahoo Finance** — 7 days max. Cannot do a 30-day backtest in a
   single shot. The current backtest_provider.py falls back to this.
   Already wired.

2. **Upstox** — 1 minute, last month only. To get 30+ days, you
   have to call the API once per day and stitch the data together,
   store locally. Same as Yahoo but with a 30-day rolling window
   instead of 7.

There is **no free provider that gives you 1-minute NSE data going
back 30+ days in a single API call**.

## Recommendation

**The honest answer: the free tier is structurally limited.**

To get a 30-day backtest on 1-minute NSE data, you must either:

1. **Stitch 30 days of Upstox data, one fetch per day, into a local
   store** — costs nothing extra, but you need an Upstox account
   with API access.

2. **Use a 30-minute interval instead of 1-minute** — Upstox returns
   1 year of 30-minute data. The strategies (momentum, reversion,
   vwap) can run on 30-minute data with degraded but not zero
   information content. This is the cheapest path to "30 days of
   backtest data".

3. **Daily interval** — Upstox returns 1 year of daily data. Almost
   useless for the strategies (need intraday volatility and session
   structure).

## The 1-minute requirement is not actually required by the strategies

Looking at the three active strategies:

- **MomentumStrategy** — uses price momentum. Works on any interval.
- **SidewaysReversionStrategy** — uses Bollinger bands. Works on
  any interval.
- **VwapReversionStrategy** — explicitly uses VWAP which is
  session-based. Needs intraday data but not 1-minute; 30-minute
  would work for a backtest.

So the cleanest answer is:

**Use Upstox 30-minute data for the 30-day backtest.** This gives
1-year of history for free, no auth complications beyond OAuth, and
is sufficient to evaluate the strategy set's expectancy.

If you have an Upstox account:
- Free, real NSE OHLCV
- 30-minute interval = 1 year history
- 1-minute interval = 1 month history
- 50 requests/sec rate limit is generous for batch backtest

If you do not have an Upstox account:
- Yahoo Finance for 1-minute gives 7 days only
- Use it for the smoke test, not for 30-day backtest
- For 30+ days, you have to pay for a paid provider (Tradable
  Patterns, NSEData, etc. — ₹2000-5000/month range)

## The path forward (action)

To enable 30-day backtest with what we have, **today**:

1. **Use 30-minute candles from Yahoo Finance** — Yahoo supports
   30-minute history at 60 days, which is enough.
2. **Verify** Yahoo 30-minute data for RELIANCE/INFY for last 60 days
3. **Switch the backtest provider** to use 30-minute instead of 1-minute
4. **Run the backtest** and see if the strategy set has positive
   expectancy

This is 30-60 min of work and gets us the answer the user wants.

To enable 1-minute 30-day backtest, **requires Upstox account**:
1. Get Upstox API credentials (account, OAuth, app)
2. Add `src/connectors/upstox/` provider
3. Wire into `BacktestDataProvider`
4. Run backtest

This is 2-4 hours and requires your action to provide credentials.

## What I'm NOT recommending

- **Don't add a paid provider for a backtest we're not sure will
  even produce a useful signal.** The strategy set might be
  unprofitable; spending money to confirm that is wasteful.
- **Don't switch from Angel to Upstox mid-session.** Angel works
  for paper/live; Upstox is a separate auth domain. Adding Upstox
  to live/paper is a bigger architectural decision that requires
  real brokerage credentials.
- **Don't use synthetic data for backtest.** The current
  backtest_provider falls back to `generate_synthetic_ticks()` if
  no real data is found. A backtest on synthetic data is not
  evidence of anything.

## The question the user actually asked

The user wants to know if the strategies are working by running a
30-day backtest. The answer to "what data provider should we use":

| If you have an Upstox account | If you don't |
|---|---|
| Use Upstox 30-minute (1 year history, free) | Use Yahoo 30-minute (60 days, free) |
| Or Upstox 1-minute (1 month, free) | Use Yahoo 1-minute (7 days, free, but only 7) |

For a **30-day backtest on 1-minute data** specifically: **you need
Upstox** (Yahoo caps at 7 days for 1-minute). For a 30-day backtest
on any interval, both work.

## Concrete next step (no Upstox required)

Change the backtest to use **30-minute candles from Yahoo**, which
gives 60 days free. That's 30 trading days × 13 candles/day = 390
candles per symbol. Enough for the strategies to fire, enough
volume to see expectancy, no credentials required.

This is the highest-ROI next action if the goal is "get a 30-day
backtest result fast and free".
