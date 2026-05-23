import pytest

from src.agents.alert import AlertAgent, LogNotifier, NtfyNotifier
from src.event_store.memory import InMemoryEventStore
from src.schemas.events import Exchange, FillEvent, OrderSide, RiskCheckEvent, SystemEvent


class CapturingNotifier(LogNotifier):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, str]] = []

    async def send(self, subject: str, message: str) -> None:
        self.sent.append((subject, message))


@pytest.fixture
def store():
    return InMemoryEventStore()


@pytest.fixture
def notifier():
    return CapturingNotifier()


@pytest.fixture
def agent(store, notifier):
    return AlertAgent(event_store=store, notifier=notifier)


@pytest.mark.asyncio
async def test_alert_start_stop(agent: AlertAgent):
    await agent.start()
    assert agent.status.value == "running"
    await agent.stop()
    assert agent.status.value == "stopped"


@pytest.mark.asyncio
async def test_alert_on_risk_breach(agent: AlertAgent, notifier: CapturingNotifier):
    await agent.start()
    event = RiskCheckEvent.create(
        check_name="max_position",
        passed=False,
        instrument="RELIANCE",
        details={"position_size": 150000, "limit": 100000, "reason": "max_position_exceeded"},
    )
    await agent.on_event(event)
    await agent.stop()
    assert len(notifier.sent) == 1
    subject, body = notifier.sent[0]
    assert subject == "RISK BREACH"
    assert "RELIANCE" in body or "instrument" in body


@pytest.mark.asyncio
async def test_alert_on_system_error(agent: AlertAgent, notifier: CapturingNotifier):
    await agent.start()
    event = SystemEvent.error("market_intel", "Connection lost")
    await agent.on_event(event)
    await agent.stop()
    assert len(notifier.sent) == 1
    subject, body = notifier.sent[0]
    assert subject == "SYSTEM ERROR"
    assert "market_intel" in body


@pytest.mark.asyncio
async def test_alert_on_fill(agent: AlertAgent, notifier: CapturingNotifier):
    await agent.start()
    import datetime
    event = FillEvent.create(
        order_id="ord_001",
        instrument="TCS",
        exchange=Exchange.NSE,
        side=OrderSide.BUY,
        fill_price=1500.0,
        fill_quantity=100,
        fill_timestamp=datetime.datetime.now(),
        trade_id="tr_001",
    )
    await agent.on_event(event)
    await agent.stop()
    assert len(notifier.sent) == 1
    subject, body = notifier.sent[0]
    assert subject == "ORDER FILL"
    assert "ord_001" in body
    assert "1500.0" in body


@pytest.mark.asyncio
async def test_ntfy_notifier_tags_and_priority():
    assert NtfyNotifier._tags_for("RISK BREACH") == "warning,rotating_light"
    assert NtfyNotifier._tags_for("SYSTEM ERROR") == "fire,no_entry"
    assert NtfyNotifier._tags_for("ORDER FILL") == "money_bag,chart_with_upwards_trend"
    assert NtfyNotifier._priority_for("RISK BREACH") == "5"
    assert NtfyNotifier._priority_for("SYSTEM ERROR") == "5"
    assert NtfyNotifier._priority_for("ORDER FILL") == "3"


@pytest.mark.asyncio
async def test_ntfy_notifier_send(agent: AlertAgent, notifier: CapturingNotifier):
    await agent.start()
    event = SystemEvent.error("test_agent", "Something broke")
    await agent.on_event(event)
    await agent.stop()
    assert len(notifier.sent) == 1
    subject, body = notifier.sent[0]
    assert subject == "SYSTEM ERROR"
    assert "test_agent" in body
    assert "Something broke" in body
