# Security Policy

## Credential Rotation

All API keys, tokens, and secrets must be rotated every 90 days.

| Credential | Env Variable | Rotation Interval | Where Used |
|---|---|---|---|
| Kite API Key | `TRA_KITE_API_KEY` | 90 days | Broker connectivity |
| Kite Access Token | `TRA_KITE_ACCESS_TOKEN` | 90 days | Broker connectivity |
| Angel API Key | `TRA_ANGEL_API_KEY` | 90 days | Market data |
| Groww API Key | `TRA_GROWW_API_KEY` | 90 days | Market data |
| Gemini API Key | `TRA_GEMINI_API_KEY` | 90 days | LLM reflection |
| Telegram Bot Token | `TRA_TELEGRAM_BOT_TOKEN` | 90 days | Alerts |
| PagerDuty Routing Key | `TRA_PAGERDUTY_ROUTING_KEY` | 90 days | Alerts |
| HTTP Auth Token | `TRA_HTTP_AUTH_TOKEN` | 90 days | API auth |

## Credential Storage

- **Local dev**: credentials in `.env` file (never committed).
- **Production**: credentials via environment variables injected by Railway.
- **Vault**: optional HashiCorp Vault or AWS Secrets Manager via `TRA_VAULT_PROVIDER` (see `src/utils/vault.py`).

## Startup Checks

On startup, the system verifies:
1. `TRA_HTTP_AUTH_TOKEN` is non-empty (all modes).
2. Kite credentials are present if `TRA_LIVE_TRADING_ENABLED=True`.
3. Credential files are less than 90 days old (logs warning if older).

## Incident Response

If credentials are compromised:
1. Revoke and rotate the affected credential immediately.
2. Update the `.env` file or Railway variable.
3. Restart the service.

## Related

- [Operations Guide](operations.md)
- [Disaster Recovery](disaster_recovery.md)
