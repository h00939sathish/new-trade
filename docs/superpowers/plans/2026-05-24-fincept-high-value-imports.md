# Fincept High-Value Imports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the useful FinceptTerminal ideas as clean-room Python components inside `new trade` without copying AGPL/commercially restricted code.

**Architecture:** Add one independent platform primitive at a time, each behind tests. Start with an in-memory data hub, then add resumable agentic task lifecycle, unified paper/live broker routing, MCP tool registry, and portfolio risk analytics.

**Tech Stack:** Python 3.12, pytest, existing `src` package, no new runtime dependency for the first slice.

---

### Task 1: Clean-Room DataHub

**Files:**
- Create: `src/datahub.py`
- Create: `tests/test_datahub.py`

- [x] **Step 1: Write failing tests**

```python
from src.datahub import DataHub, TopicPolicy


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_publish_updates_cache_and_subscribers():
    clock = Clock()
    hub = DataHub(clock=clock)
    seen = []

    hub.subscribe("market:NSE:RELIANCE", seen.append)
    hub.publish("market:NSE:RELIANCE", {"last": 100.0})

    assert hub.peek("market:NSE:RELIANCE") == {"last": 100.0}
    assert seen == [{"last": 100.0}]


def test_peek_honors_ttl_but_peek_raw_returns_last_known_good():
    clock = Clock()
    hub = DataHub(clock=clock)
    hub.set_policy("market:NSE:RELIANCE", TopicPolicy(ttl_seconds=10))

    hub.publish("market:NSE:RELIANCE", 100.0)
    clock.now += 11

    assert hub.peek("market:NSE:RELIANCE") is None
    assert hub.peek_raw("market:NSE:RELIANCE") == 100.0


def test_pattern_subscription_receives_matching_topics_only():
    hub = DataHub()
    seen = []

    hub.subscribe_pattern("market:NSE:*", lambda topic, value: seen.append((topic, value)))
    hub.publish("market:NSE:RELIANCE", 100.0)
    hub.publish("market:BSE:RELIANCE", 101.0)

    assert seen == [("market:NSE:RELIANCE", 100.0)]


def test_request_uses_registered_producer_and_records_stats():
    hub = DataHub()
    calls = []

    def refresh(topic: str):
        calls.append(topic)
        return {"topic": topic}

    hub.register_producer("market:*", refresh)

    assert hub.request("market:NSE:TCS") == {"topic": "market:NSE:TCS"}
    assert hub.peek("market:NSE:TCS") == {"topic": "market:NSE:TCS"}

    stats = hub.stats()["market:NSE:TCS"]
    assert stats.total_publishes == 1
    assert stats.last_refresh_seconds > 0
    assert calls == ["market:NSE:TCS"]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_datahub.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'src.datahub'`.

- [x] **Step 3: Implement minimal `DataHub`**

Create a dependency-free module with `TopicPolicy`, `TopicStats`, and `DataHub`. It must support exact subscription, wildcard suffix subscription, TTL-aware `peek`, stale `peek_raw`, producer registration, refresh via `request`, and stats.

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_datahub.py -q`

Expected: all tests pass.

### Task 2: Resumable Agentic Task Lifecycle

**Files:**
- Create: `src/agentic/tasks.py`
- Create: `tests/test_agentic_tasks.py`

- [x] Build a SQLite-backed task lifecycle with `start`, `save_checkpoint`, `pause_requested`, `cancel_requested`, `resume`, emitted step events, and budget caps. Do not give it order placement privileges.

### Task 3: Unified Paper/Live Broker Router

**Files:**
- Create: `src/execution/router.py`
- Create: `tests/test_execution_router.py`

- [x] Add a clean broker router that can route to paper or live adapters through one command object and blocks live orders unless an explicit safety gate passes.

### Task 4: MCP Tool Registry

**Files:**
- Create: `src/mcp_tools/registry.py`
- Create: `tests/test_mcp_tool_registry.py`

- [x] Add a schema-first internal tool registry for safe read-only operations first: health, portfolio snapshot, event replay, recent risk checks.

### Task 5: Portfolio Risk Analytics

**Files:**
- Create: `src/risk/analytics.py`
- Create: `tests/test_risk_analytics.py`

- [x] Add deterministic portfolio risk analytics: historical VaR, max drawdown, exposure concentration, simple risk budget checks, and audit-friendly result objects.
