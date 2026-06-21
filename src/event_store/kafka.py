import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from src.event_store.base import EventStore
from src.schemas.events import Event

logger = logging.getLogger("event_store.kafka")

logger.warning(
    "DEPRECATED: KafkaEventStore is unused and has no active code path. "
    "It will be removed in a future release. Use SqliteEventStore or PostgresEventStore instead."
)


class KafkaEventStore(EventStore):
    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "trading-system",
    ):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self._producer: AIOKafkaProducer | None = None
        self._consumers: dict[str, AIOKafkaConsumer] = {}

    async def connect(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            enable_idempotence=True,
            acks="all",
        )
        await self._producer.start()

    async def disconnect(self) -> None:
        for consumer in self._consumers.values():
            await consumer.stop()
        self._consumers.clear()
        if self._producer:
            await self._producer.stop()
            self._producer = None

    def _get_producer(self) -> AIOKafkaProducer:
        if self._producer is None:
            msg = "Event store not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._producer

    async def append(self, stream: str, event: Event) -> int:
        producer = self._get_producer()
        topic = self._stream_to_topic(stream)
        key = event.event_id.encode()
        value = json.dumps(
            {
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "stream": stream,
                "timestamp": event.timestamp.isoformat(),
                "data": event.data,
                "metadata": event.metadata.model_dump(mode="json"),
            }
        ).encode()
        future = await producer.send(topic, key=key, value=value)
        result = await future
        event.position = result.offset
        return result.offset

    async def append_batch(self, stream: str, events: list[Event]) -> list[int]:
        positions: list[int] = []
        for event in events:
            pos = await self.append(stream, event)
            positions.append(pos)
        return positions

    async def read(
        self,
        stream: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        topic = self._stream_to_topic(stream)
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=f"{self.group_id}-reader",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await consumer.start()
        try:
            consumer.seek(topic.partition, offset)  # type: ignore
            events: list[Event] = []
            msg_count = 0
            async for msg in consumer:
                if msg_count >= limit:
                    break
                data = json.loads(msg.value.decode())
                event = Event(
                    event_id=data["event_id"],
                    event_type=data["event_type"],
                    stream=data["stream"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    data=data["data"],
                    metadata=data["metadata"],
                    position=msg.offset,
                )
                events.append(event)
                msg_count += 1
            return events
        finally:
            await consumer.stop()

    async def replay(
        self,
        stream: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> AsyncIterator[Event]:
        msg = "Kafka replay requires specific stream; use direct consumer instead"
        raise NotImplementedError(msg)

    async def get_latest(self, stream: str) -> Event | None:
        topic = self._stream_to_topic(stream)
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=f"{self.group_id}-latest",
            auto_offset_reset="latest",
            enable_auto_commit=False,
        )
        await consumer.start()
        try:
            end_offsets = await consumer.end_offsets([topic.partition])  # type: ignore
            last_offset = end_offsets[topic.partition] - 1  # type: ignore
            if last_offset < 0:
                return None
            consumer.seek(topic.partition, last_offset)  # type: ignore
            async for msg in consumer:
                data = json.loads(msg.value.decode())
                return Event(
                    event_id=data["event_id"],
                    event_type=data["event_type"],
                    stream=data["stream"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    data=data["data"],
                    metadata=data["metadata"],
                    position=msg.offset,
                )
            return None
        finally:
            await consumer.stop()

    async def get_stream_names(self) -> list[str]:
        if self._producer is None:
            return []
        cluster = await self._producer.client.fetch_all_metadata()
        return [t for t in cluster.topics() if t.startswith("trading.")]

    async def get_stream_length(self, stream: str) -> int:
        topic = self._stream_to_topic(stream)
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=f"{self.group_id}-length",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await consumer.start()
        try:
            end_offsets = await consumer.end_offsets([topic.partition])  # type: ignore
            return end_offsets[topic.partition]  # type: ignore
        finally:
            await consumer.stop()

    async def delete_stream(self, stream: str) -> None:
        pass

    async def health_check(self) -> dict[str, Any]:
        try:
            producer = self._get_producer()
            metadata = await producer.client.fetch_all_metadata()
            broker_count = len(metadata.brokers())
            return {
                "status": "healthy",
                "type": "kafka",
                "brokers": broker_count,
            }
        except Exception as e:
            return {"status": "unhealthy", "type": "kafka", "error": str(e)}

    def _stream_to_topic(self, stream: str) -> str:
        return f"trading.{stream.replace('.', '_')}"
