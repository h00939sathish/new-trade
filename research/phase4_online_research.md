# Phase 4: Online Research

---

## 1. NSE/SEBI Regulatory Landscape (as of June 2026)

### Algorithmic Trading Framework
- **Static IP mandate** (Angel: Apr 2026, Kite: Apr 2025): All order API requests must originate from registered static IP. Non-compliance = order rejection.
- **OAuth requirement** (SEBI circular Aug 2025): Brokers must implement OAuth-based authentication only. Legacy password login being phased out.
- **10 orders/second limit**: Hard limit at exchange level. Exceeding triggers registration requirement.
- **Algo registration**: Required if orders per second exceed 10. Separate registration per exchange.
- **System audit**: Every 6 months by CISA/DISA/CISM/CISSP auditor. Scope includes risk management, audit trail, cyber security per SEBI CSCRF.
- **Audit trail retention**: Minimum 5 years for all algo orders and trades.
- **SEBI CSCRF**: Comprehensive cyber security framework for regulated entities. Covers asset management, vulnerability management, incident response, access control.

### Key Sources
- NSE Circular INSP71214 (Nov 2025): CSCRF implementation timelines
- NSE Circular INVG67858 (Feb 2025): Retail algo participation implementation standards
- SEBI Circular Aug 2024: CSCRF for SEBI regulated entities

## 2. Broker API Landscape

### Angel One SmartAPI
- API key + password + TOTP → JWT (1hr) + Refresh token
- Static IP required for orders from Apr 2026
- Rate limit: 10 OPS on order APIs
- Session auto-expires at midnight; must re-login daily
- WebSocket: binary protocol (51-byte packet header), supports LTP/QUOTE/SNAP_QUOTE/DEPTH modes
- Symbol master: JSON file hosted on GitHub (~5MB, 5000+ instruments)
- Historical: 1m/3m/5m/15m/30m/1h/1d intervals

### Kite Connect (Zerodha)
- OAuth flow: API key + request_token + checksum → access_token (daily, expires 6 AM IST)
- Public token available for read-only access
- Static IP required for orders from Apr 2025
- Rate limit: 10 OPS on order APIs, 250 req/min on REST
- WebSocket: tick-by-tick streaming for up to 3000 instruments
- Historical: minute/day data
- No OAuth SDK — login via browser redirect

### Groww
- API is less documented and less stable
- No official Python SDK
- TOTP-based authentication

### Jugaad Data
- `jugaad_data` Python library for NSE bhavcopy
- Daily historical data only (EOD)
- No intraday data via bhavcopy
- Reliable for long-term backtests

## 3. Technology Stack Context

### Python asyncio for Trading
- Asyncio is appropriate for I/O-bound trading systems (network I/O for broker APIs)
- Pure Python/GIL-bound numpy operations block the event loop
- Typical latency budget for NSE algo: <100ms from tick to order
- Python is used by ~60% of retail algo traders in India (Angel/Kite SDKs are Python-first)

### Backtesting Practices
- Walk-forward optimization is industry standard for parameter robustness
- Grid search without cross-validation leads to overfitting
- Triple Barrier Meta Labeling (from Marcos López de Prado) is the gold standard for financial ML labeling — stub implementation exists but unused
- HRP is superior to mean-variance optimization for correlated assets

## 4. NSE Market Structure (2026)

- **Trading hours**: 9:15-15:30 IST (cash market)
- **Pre-open**: 9:00-9:15 (order collection + matching)
- **Settlement**: T+1 (since Jan 2023)
- **Market timings only relevant for paper trading** — no overnight holding in current system
- **F&O expiry**: Weekly on Thursdays (for most indices), monthly for single-stock futures
- **SEBI introduced 'Safer Participation of Retail Algo Trading'** — the regulatory driver behind all the changes above
