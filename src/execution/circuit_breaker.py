import asyncio
import enum
import logging

logger = logging.getLogger("execution.circuit_breaker")


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker for broker/data-source connections.

    States:
      CLOSED   - normal operation, requests pass through
      OPEN     - failures exceeded threshold, requests blocked
      HALF_OPEN - after cooldown, one probe request allowed
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ):
        self._name = name
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._half_open_event: asyncio.Event | None = None

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED

    def record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker %s: HALF_OPEN probe succeeded → CLOSED", self._name)
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            if self._half_open_event:
                self._half_open_event.set()
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        from datetime import UTC, datetime

        self._last_failure_time = datetime.now(UTC).timestamp()
        if self._state == CircuitState.HALF_OPEN:
            logger.warning("Circuit breaker %s: HALF_OPEN probe failed → OPEN", self._name)
            self._state = CircuitState.OPEN
            self._failure_count += 1
            return
        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            logger.warning(
                "Circuit breaker %s: %d failures → OPEN",
                self._name,
                self._failure_count,
            )
            self._state = CircuitState.OPEN
            self._half_open_event = asyncio.Event()

    async def wait_for_cooldown(self) -> None:
        if self._state != CircuitState.OPEN:
            return
        from datetime import UTC, datetime

        if self._last_failure_time is None:
            return
        elapsed = datetime.now(UTC).timestamp() - self._last_failure_time
        remaining = max(0.0, self._cooldown_seconds - elapsed)
        if remaining > 0:
            logger.info(
                "Circuit breaker %s: waiting %.0fs before HALF_OPEN probe",
                self._name,
                remaining,
            )
            await asyncio.sleep(remaining)
        self._state = CircuitState.HALF_OPEN
        logger.info("Circuit breaker %s: OPEN → HALF_OPEN (probe allowed)", self._name)

    async def attempt_probe(self) -> bool:
        """Returns True if a probe request is allowed (HALF_OPEN state)."""
        await self.wait_for_cooldown()
        return self._state == CircuitState.HALF_OPEN

    async def __aenter__(self):
        await self.wait_for_cooldown()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.record_failure()
        else:
            self.record_success()
