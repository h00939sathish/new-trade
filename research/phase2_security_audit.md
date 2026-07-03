# Phase 2: Security Audit

**Date**: 2026-06-30 | **Auditor**: AI-assisted code review + SEBI/NSE circular analysis

---

## 1. Credential Management

### Current State
| Credential | Storage | Encryption | Rotation | Risk |
|-----------|---------|------------|----------|------|
| Angel API Key | `TRA_ANGEL_API_KEY` env var | Plaintext | Manual | Moderate |
| Angel Password | `TRA_ANGEL_PASSWORD` env var | Plaintext | Manual | High |
| Angel TOTP Secret | `TRA_ANGEL_TOTP` env var | Plaintext | Manual | Critical |
| Kite API Key | `TRA_KITE_API_KEY` env var | Plaintext | Manual | Moderate |
| Kite Access Token | `TRA_KITE_ACCESS_TOKEN` env var | Plaintext | Manual | High |
| Groww API Key/Secret | `TRA_GROWW_*` env vars | Plaintext | Manual | Moderate |
| Railway Deploy Tokens | `RAILWAY_*` env vars | Plaintext | — | Low (platform-managed) |

### Issues
1. **[CRITICAL] TOTP Secret in Plaintext**: `src/connectors/angel/client.py:101-106` reads `_totp` from env and generates TOTP codes via `pyotp.TOTP(self._totp).now()`. If env vars leak, the TOTP seed gives permanent 2FA bypass.
2. **[HIGH] No Secrets Encryption at Rest**: All 27+ `TRA_*` credentials stored as plaintext env vars. No vault, no HSM, no encrypted config file. `src/utils/vault.py` is a stub.
3. **[HIGH] Access Tokens in Env Vars**: Kite access token is stored in env vars — should be refreshed daily (expires at 6 AM IST per Zerodha policy). Current code never refreshes it; if the token expires, all API calls fail silently with placeholder mode.
4. **[MODERATE] Process Memory Exposure**: Credentials in env vars are visible in `/proc/*/environ` on Linux (Railway). Any process compromise leaks all broker credentials.
5. **[LOW] .env File in Git Risk**: `settings.py` loads from `.env` file. Need to verify `.env` is in `.gitignore`.

## 2. Network Security

### Current State
- **No static IP registered**: Angel requires static IP from April 1, 2026 for order execution (per NSE/SEBI circular). Kite requires static IP from April 1, 2025. Current code has no IP whitelist awareness.
- **Angel public IP leak**: `src/connectors/angel/client.py:304-314` calls `ifconfig.me/ip` on every HTTP request — leaks client IP to third-party service.
- **No TLS certificate pinning**: All HTTPS connections use system CA trust store.
- **Yahoo Finance no auth**: `src/connectors/yahoo.py` uses public API — no rate limit protection, IP blocks possible.

### Issues
1. **[CRITICAL] Static IP Non-Compliance**: Angel and Kite both require registered static IP for order placement (Angel from April 2026, Kite from April 2025). System has no static IP registration — orders will be rejected in live trading.
2. **[HIGH] Angel IP Leak**: `_resolve_public_ip()` sends IP to `ifconfig.me` on every auth header build. Privacy risk, dependency on external service availability.
3. **[MODERATE] Yahoo Finance Rate Limiting**: No retry with backoff for Yahoo 429 responses — backtest data fetches may fail silently.

## 3. Authentication & Authorization

### Current Flow
- **Angel**: API Key + Password + TOTP → JWT token (1-hour expiry) + Refresh token
- **Kite**: API Key + Access Token → Session (daily expiry, 6 AM IST)
- **Groww**: API Key + Secret + TOTP → Auth token
- **No OAuth**: All use legacy API key auth, not OAuth. SEBI mandates OAuth-based auth from August 2025.

### Issues
1. **[HIGH] No OAuth**: SEBI circular mandates "OAuth based authentication only" for API connectivity. System uses legacy password-based auth for all brokers.
2. **[HIGH] Session Not Terminated on Shutdown**: Kite `disconnect()` calls `session.destroy()` but Angel `disconnect()` only closes HTTP client — doesn't invalidate JWT token server-side (`logout` API not called).
3. **[MODERATE] No Rate Limiting on Auth Endpoints**: No protection against credential brute-force.

## 4. Authorization & Access Control

### Current State
- **No RBAC**: Single process runs with all privileges. No user roles.
- **No audit logging of credential access**: `settings.py` loads credentials silently.
- **Paper mode bypass**: When credentials missing, system falls back to paper mode — silent degradation, no security alert.
- **No API key rotation**: Credentials never rotated unless manually updated.

### Issues
1. **[MODERATE] No Access Audit Log**: Who accessed which credential when — no tracking.
2. **[MODERATE] Silent Degradation to Paper**: Attackers could delete env vars and system would run in paper mode without alerting operator.
3. **[LOW] No Credential Rotation Policy**: Angel keys, Kite secrets never auto-rotated.

## 5. Data Security

### Current State
- **SQlite databases**: `state/order_state.db`, `state/trading_events.db`, `state/kill_switch.state`, `state/angel_symbols.json` — unencrypted on disk.
- **Event store**: No encryption at rest.
- **Backup/Restore**: No backup mechanism for state data.

### Issues
1. **[MODERATE] Unencrypted SQLite Databases**: All state files in clear text. On shared hosting (Railway), other containers could potentially read files.
2. **[LOW] No Data Backup**: Order history, trade logs — no backup, no DR plan.
3. **[LOW] State Persistence on Ephemeral FS**: Railway filesystem is ephemeral — state lost on deploy. Only `order_state.db` persists (bind mount).

## 6. SEBI/NSE Compliance Gaps

| Requirement | Status | Gap |
|------------|--------|-----|
| Static IP for orders (Angel Apr 2026) | ❌ Not implemented | Orders will be rejected |
| Static IP for orders (Kite Apr 2025) | ❌ Not implemented | Orders will be rejected |
| OAuth authentication | ❌ Password-based | Non-compliant |
| 10 OPS limit | ⚠️ No throttling | Could exceed exchange limits |
| Algo registration (>10 OPS) | ❌ Not addressed | Risk of exchange penalties |
| System audit every 6 months | ❌ No audit trail | Non-compliant |
| Audit trail (5 years) | ❌ No long-term retention | Non-compliant |
| 2FA enforcement | ⚠️ TOTP supported but in plaintext | Non-compliant |
| SEBI CSCRF cyber security | ❌ Not addressed | Non-compliant |

## 7. Vulnerability Summary

| ID | Severity | Finding | Subsystem | Mitigation |
|----|----------|---------|-----------|------------|
| SEC-01 | CRITICAL | TOTP secret in plaintext env var | Angel connector | Use vault/HSM or encrypt at rest |
| SEC-02 | CRITICAL | Static IP not registered for any broker | All brokers | Register static IP, validate at startup |
| SEC-03 | HIGH | No OAuth (SEBI mandate) | All brokers | Implement OAuth login flow |
| SEC-04 | HIGH | Session not terminated on shutdown | Angel client | Call logout API |
| SEC-05 | HIGH | IP leak via ifconfig.me | Angel client | Remove or localize IP resolution |
| SEC-06 | HIGH | Kite access token never refreshed | Kite client | Auto-refresh daily before 6 AM |
| SEC-07 | MODERATE | Credentials in process memory | Core | Use env-only, minimize exposure |
| SEC-08 | MODERATE | No audit log of credential access | Settings | Add access logging |
| SEC-09 | MODERATE | SQLite state files unencrypted | Risk/Execution | Encrypt at rest |
| SEC-10 | MODERATE | Paper mode allows silent degradation | System | Alert on credential failure |
| SEC-11 | MODERATE | No rate limiting on auth endpoints | API | Add rate limiting |
| SEC-12 | LOW | No backup mechanism | All state | Add backup to S3/cloud storage |

## 8. Regulatory Compliance Path

### Required for Live Trading (by priority)
1. **[Apr 2026 deadline - OVERDUE]** Register static IP with Angel One SmartAPI dashboard
2. **[Apr 2025 deadline - OVERDUE]** Register static IP with Kite Connect
3. Implement OAuth login flow (SEBI mandate)
4. Add order rate limiting (≤10 OPS per SEBI/NSE)
5. Implement audit trail with 5-year retention
6. Conduct formal system audit (CISA/DISA/CISM/CISSP auditor)
7. Register algorithm if OPS exceeds 10

### Recommendations
- Use `python-dotenv` + encrypted `.env.vault` (Ansible Vault or similar)
- Replace `ifconfig.me` with local network detection
- Add pre-flight check at startup: validates static IP, OAuth tokens, broker connectivity
- Implement credential rotation cron job (29-day for Angel, daily for Kite)
