import asyncio
import logging
import os
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from src.config.settings import settings
from src.event_store import EventStore, create_event_store
from src.schemas.events import Event, EventType, SystemEvent


class AgentStatus(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class Agent(ABC):
    name: str
    status: AgentStatus
    event_store: EventStore
    logger: logging.Logger

    @abstractmethod
    async def on_start(self) -> None: ...
    @abstractmethod
    async def on_stop(self) -> None: ...
    @abstractmethod
    async def on_event(self, event: Event) -> None: ...
    @abstractmethod
    async def health(self) -> dict[str, Any]: ...


SYSTEM_BUS = "events.bus"


class BaseAgent(Agent):
    def __init__(self, name: str, log_level: str | None = None, event_store: EventStore | None = None):
        self.name = name
        self.status = AgentStatus.CREATED
        self.event_store = event_store or create_event_store()
        self._subscribed_event_types: set[EventType] = set()
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._health_emit_interval_seconds = max(
            0.01,
            float(os.getenv("TRA_AGENT_HEARTBEAT_SECONDS", "30")),
        )

        self.logger = logging.getLogger(f"agent.{name}")
        self.logger.setLevel(log_level or settings.log_level)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            self.logger.addHandler(handler)

    async def start(self, run_background_loop: bool = True) -> None:
        self.status = AgentStatus.STARTING
        self.logger.info("Agent starting...")
        try:
            await self.event_store.connect()
            from src.event_store.async_bus import event_bus
            event_bus.set_event_store(self.event_store)

            await self.on_start()
            self.status = AgentStatus.RUNNING
            self._running = True
            if run_background_loop:
                task = asyncio.create_task(
                    self._subscribe_bus_loop(), name=f"{self.name}.bus"
                )
                self._tasks.append(task)
            self._tasks.append(
                asyncio.create_task(
                    self._health_emit_loop(),
                    name=f"{self.name}.health",
                )
            )
            self.logger.info("Agent started successfully")
            await self._emit_health()
        except Exception as e:
            self.status = AgentStatus.ERROR
            self.logger.error("Failed to start: %s", e, exc_info=True)
            raise

    async def stop(self) -> None:
        self.status = AgentStatus.STOPPING
        self.logger.info("Agent stopping...")
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.on_stop()
        self.status = AgentStatus.STOPPED
        self.logger.info("Agent stopped")

    async def run_forever(self) -> None:
        self._running = True
        task = asyncio.create_task(
            self._subscribe_bus_loop(), name=f"{self.name}.bus"
        )
        self._tasks.append(task)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    def subscribe(self, event_type: EventType) -> None:
        self._subscribed_event_types.add(event_type)

    def subscribe_all(self) -> None:
        for et in EventType:
            self._subscribed_event_types.add(et)

    def subscribe_market_data(self) -> None:
        self.subscribe(EventType.TICK)
        self.subscribe(EventType.OHLCV)

    def subscribe_signals(self) -> None:
        self.subscribe(EventType.SIGNAL)

    def subscribe_orders(self) -> None:
        self.subscribe(EventType.ORDER_CREATED)
        self.subscribe(EventType.ORDER_ACCEPTED)
        self.subscribe(EventType.ORDER_REJECTED)
        self.subscribe(EventType.ORDER_CANCELLED)

    def subscribe_risk(self) -> None:
        self.subscribe(EventType.RISK_CHECK)
        self.subscribe(EventType.RISK_BREACH)

    def subscribe_system(self) -> None:
        self.subscribe(EventType.SYSTEM_HEALTH)
        self.subscribe(EventType.SYSTEM_ERROR)
        self.subscribe(EventType.SYSTEM_STATE)

    async def emit(self, event: Event) -> None:
        from src.event_store.async_bus import event_bus
        await event_bus.publish(event)
        try:
            from src.monitoring.metrics import system_metrics
            system_metrics.count_event(event.event_type.value)
        except Exception:
            pass

    def interested_in(self, event_type: EventType) -> bool:
        return event_type in self._subscribed_event_types

    async def _subscribe_bus_loop(self) -> None:
        self.logger.info(
            "Listening on event bus for types: %s",
            [e.value for e in self._subscribed_event_types],
        )
        import time

        from src.event_store.async_bus import event_bus
        self._queue = event_bus.subscribe(self.name, self._subscribed_event_types)

        while self._running:
            try:
                event = await self._queue.get()  # Blocks until event arrives (Bug 3.3)

                # Skip events produced by this agent itself to avoid feedback loops (Bug 2.5)
                if event.metadata and event.metadata.producer == self.name:
                    continue
                if self.interested_in(event.event_type):
                    try:
                        start_time = time.monotonic()
                        await self.on_event(event)
                        latency = time.monotonic() - start_time
                        try:
                            from src.monitoring.metrics import system_metrics
                            system_metrics.record_latency(latency)
                        except Exception:
                            pass
                    except Exception as e:
                        self.logger.error(
                            "Error handling event %s: %s",
                            event.event_id, e, exc_info=True,
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Bus subscription error: %s", e, exc_info=True)
                await asyncio.sleep(1)

    async def _emit_health(self) -> None:
        health = await self.health()
        event = SystemEvent.health(self.name, "running", health)
        await self.emit(event)

    async def _health_emit_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._health_emit_interval_seconds)
                if not self._running:
                    break
                await self._emit_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Health emission error: %s", e, exc_info=True)

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass

    async def health(self) -> dict[str, Any]:
        store_health = await self.event_store.health_check()
        return {
            "agent": self.name,
            "status": self.status.value,
            "event_store": store_health,
            "subscribed_types": [e.value for e in self._subscribed_event_types],
        }
