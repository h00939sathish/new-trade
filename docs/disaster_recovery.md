# Disaster Recovery Runbook

## 1. SQLite Corruption

**Symptoms:** `sqlite3.DatabaseError` or `database disk image is malformed` in logs.

**Recovery:**
```bash
# 1. Stop the system
docker compose down

# 2. Restore from latest backup
cp state/trading.db.backup state/trading.db

# 3. Verify integrity
sqlite3 state/trading.db "PRAGMA integrity_check;"

# 4. Restart
docker compose up -d
```

**If no backup exists:**
```bash
# 1. Attempt .dump recovery
sqlite3 state/trading.db ".dump" > recovery.sql
# 2. Create fresh DB
sqlite3 state/trading_new.db < recovery.sql
# 3. Validate
mv state/trading_new.db state/trading.db
```

**Prevention:** Enable WAL mode (already default in SqliteEventStore). Schedule daily backups.

## 2. Event Store Failure

**Symptoms:** Events not persisting, `EventStore` errors in logs.

**Recovery:**
1. Check which store is active (`TRA_EVENT_STORE_TYPE`).
2. For SQLite: follow Section 1.
3. For Postgres:
   ```bash
   docker compose exec postgres psql -U trading -c "SELECT count(*) FROM events;"
   docker compose restart trading-app
   ```
4. If store is unrecoverable, switch to in-memory store:
   ```bash
   export TRA_EVENT_STORE_TYPE=memory
   python -m src.main
   ```
   Note: In-memory store loses all history on restart.

## 3. Broker API Outage

**Symptoms:** `BrokerError`, timeout on `place_order`, `get_positions` failures.

**Recovery:**
1. Kill switch activates automatically if P&L drops below threshold.
2. If kill switch does not activate:
   ```bash
   curl -X POST http://localhost:8080/api/kill-switch/reset -H "Authorization: Bearer $TRA_HTTP_AUTH_TOKEN"
   ```
3. Manual position reconciliation:
   ```bash
   python -m src.agents.reconciliation --force
   ```
4. Once broker API recovers, verify positions match:
   ```bash
   curl http://localhost:8080/health | jq '.reconciliation'
   ```

## 4. System Crash Mid-Order

**Symptoms:** System restarts with orders in unknown state.

**Recovery (automatic):**
1. On restart, `ExecutionAgent._load_outstanding_orders()` restores pending orders.
2. If live broker connected, `reconcile_orders()` checks order status on broker.
3. Manual check:
   ```bash
   curl http://localhost:8080/api/orders/pending
   ```

## 5. Power Loss / Docker Crash

**Symptoms:** Container stopped unexpectedly, state files on disk.

**Recovery:**
```bash
docker compose down
# Check for corrupted SQLite
sqlite3 state/trading.db "PRAGMA integrity_check;"
docker compose up -d
# Verify kill-switch state
curl http://localhost:8080/health | jq '.kill_switch'
```

## 6. Data Loss (All Stores)

**Recovery:**
1. Replay events from last known-good snapshot:
   ```bash
   python scripts/replay_events.py --from "2024-01-01" --to "2024-12-31"
   ```
2. Verify position state matches broker:
   ```bash
   python -m src.agents.reconciliation --force
   ```

## Escalation

| Issue | Contact | SLA |
|---|---|---|
| Kill switch failure | On-call engineer | 15 min |
| Broker API outage | Broker support + on-call | 1 hour |
| Data loss | Engineering lead | 4 hours |
| Security breach | Security team + on-call | Immediate |

## Prevention

- Daily automated backups of `state/` directory.
- Kill switch integration tests run in CI.
- Event store integrity check on startup.
- Monitoring alerts on broker connection drops.
