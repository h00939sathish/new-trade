from src.config.settings import settings
from src.event_store.base import EventStore, EventStoreConfig
from src.event_store.sqlite import SqliteEventStore


def create_event_store() -> EventStore:
    match settings.event_store_type:
        case "postgres":
            from src.event_store.postgres import PostgresEventStore as Store
            return Store(settings.postgres_dsn)
        case "sqlite":
            return SqliteEventStore()
        case "memory":
            from src.event_store.memory import InMemoryEventStore
            return InMemoryEventStore()
        case _:
            msg = f"Unknown event store type: {settings.event_store_type}"
            raise ValueError(msg)


__all__ = [
    "EventStore",
    "EventStoreConfig",
    "SqliteEventStore",
    "create_event_store",
]
