import logging
import time
from typing import Any

import httpx

from src.agents.base import BaseAgent
from src.config.settings import settings
from src.event_store import EventStore
from src.schemas.events import Event, EventType


class Notifier:
    async def send(self, subject: str, message: str) -> None: ...


class LogNotifier(Notifier):
    def __init__(self) -> None:
        self.logger = logging.getLogger("alert")

    async def send(self, subject: str, message: str) -> None:
        self.logger.warning("ALERT [%s]: %s", subject, message)


class TelegramNotifier(Notifier):
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self.logger = logging.getLogger("alert.telegram")

    async def send(self, subject: str, message: str) -> None:
        text = f"[{subject}] {message}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{self._token}/sendMessage",
                    json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
                    timeout=10,
                )
                resp.raise_for_status()
        except Exception as e:
            self.logger.error("Telegram send failed: %s", e)


class NtfyNotifier(Notifier):
    def __init__(self, topic: str, server: str = "https://ntfy.sh") -> None:
        self._topic = topic
        self._server = server.rstrip("/")
        self.logger = logging.getLogger("alert.ntfy")

    async def send(self, subject: str, message: str) -> None:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._server}/{self._topic}",
                    content=message,
                    headers={
                        "Title": subject,
                        "Tags": self._tags_for(subject),
                        "Priority": self._priority_for(subject),
                    },
                    timeout=10,
                )
                resp.raise_for_status()
        except Exception as e:
            self.logger.error("ntfy.sh send failed: %s", e)

    @staticmethod
    def _tags_for(subject: str) -> str:
        if "RISK" in subject:
            return "warning,rotating_light"
        if "ERROR" in subject:
            return "fire,no_entry"
        if "FILL" in subject:
            return "money_bag,chart_with_upwards_trend"
        return "bell"

    @staticmethod
    def _priority_for(subject: str) -> str:
        if "RISK" in subject or "ERROR" in subject:
            return "5"
        if "FILL" in subject:
            return "3"
        return "3"


class PagerDutyNotifier(Notifier):
    def __init__(self, routing_key: str) -> None:
        self._routing_key = routing_key
        self.logger = logging.getLogger("alert.pagerduty")

    async def send(self, subject: str, message: str) -> None:
        severity = "critical" if "RISK" in subject or "ERROR" in subject else "info"
        dedup_key = f"trading-system-{subject.replace(' ', '-').lower()}"

        payload = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "dedup_key": dedup_key,
            "payload": {
                "summary": f"[{subject}] {message[:100]}",
                "source": "trading-system",
                "severity": severity,
                "custom_details": {"subject": subject, "message": message},
            },
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://events.pagerduty.com/v2/enqueue",
                    json=payload,
                    timeout=10,
                )
                resp.raise_for_status()
        except Exception as e:
            self.logger.error("PagerDuty send failed: %s", e)


class MultiNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier]) -> None:
        self._notifiers = notifiers

    async def send(self, subject: str, message: str) -> None:
        for notifier in self._notifiers:
            await notifier.send(subject, message)


def create_notifier() -> Notifier:
    notifiers: list[Notifier] = []
    if settings.pagerduty_routing_key:
        notifiers.append(PagerDutyNotifier(settings.pagerduty_routing_key))
    if settings.telegram_bot_token and settings.telegram_chat_id:
        notifiers.append(TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id))
    if settings.ntfy_topic:
        notifiers.append(NtfyNotifier(settings.ntfy_topic, settings.ntfy_server))

    if not notifiers:
        return LogNotifier()
    if len(notifiers) == 1:
        return notifiers[0]
    return MultiNotifier(notifiers)


class AlertAgent(BaseAgent):
    def __init__(
        self,
        event_store: EventStore | None = None,
        notifier: Notifier | None = None,
    ):
        super().__init__(name="alert", event_store=event_store)
        self._notifier = notifier or create_notifier()
        self._last_alert_times: dict[EventType, float] = {}
        self._rate_limit_seconds = 60.0

    async def on_start(self) -> None:
        self.logger.info("Alert Agent initializing")
        self.subscribe(EventType.RISK_BREACH)
        self.subscribe(EventType.SYSTEM_ERROR)
        self.subscribe(EventType.FILL)
        self.subscribe(EventType.SYSTEM_HEALTH)

    async def on_stop(self) -> None:
        self.logger.info("Alert Agent stopping")

    async def on_event(self, event: Event) -> None:
        now = time.time()
        last_sent = self._last_alert_times.get(event.event_type, 0.0)
        if now - last_sent < self._rate_limit_seconds:
            self.logger.debug("Rate limiting alert for event %s", event.event_type.value)
            return

        match event.event_type:
            case EventType.RISK_BREACH:
                self._last_alert_times[event.event_type] = now
                await self._notifier.send(
                    "RISK BREACH",
                    self._format(event.data),
                )
            case EventType.SYSTEM_ERROR:
                self._last_alert_times[event.event_type] = now
                await self._notifier.send(
                    "SYSTEM ERROR",
                    self._format(event.data),
                )
            case EventType.FILL:
                self._last_alert_times[event.event_type] = now
                await self._notifier.send(
                    "ORDER FILL",
                    self._format(event.data),
                )

    @staticmethod
    def _format(data: dict[str, Any]) -> str:
        return "\n".join(f"{k}: {v}" for k, v in data.items())
