import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_STALE_DATA_TIMEOUT = 120.0
_DUPLICATE_WINDOW = 60.0
_RECONNECT_BASE_DELAY = 1.0
_RECONNECT_MAX_DELAY = 60.0


class StaleDataWatchdog:
    def __init__(self, timeout: float = _STALE_DATA_TIMEOUT):
        self._timeout = timeout
        self._last_tick: dict[str, float] = {}
        self._blocked: bool = False

    def check_freshness(self, instrument: str, last_tick_time: float) -> bool:
        now = time.time()
        elapsed = now - last_tick_time
        if elapsed > self._timeout:
            self._last_tick[instrument] = last_tick_time
            logger.warning(
                "Stale data for %s: %.1fs since last tick (threshold=%.0fs)",
                instrument,
                elapsed,
                self._timeout,
            )
            return False
        self._last_tick[instrument] = last_tick_time
        return True

    def block_if_stale(self) -> bool:
        now = time.time()
        for instrument, last_time in list(self._last_tick.items()):
            if now - last_time > self._timeout:
                self._blocked = True
                logger.warning(
                    "Blocking entries: stale data for %s (%.1fs ago)",
                    instrument,
                    now - last_time,
                )
                return True
        self._blocked = False
        return False


class DuplicateOrderProtector:
    def __init__(self, window: float = _DUPLICATE_WINDOW):
        self._window = window
        self._recent: set[tuple[str, str, float, float]] = set()

    def is_duplicate(
        self, instrument: str, side: str, price: float, timestamp: float | None = None
    ) -> bool:
        key = (instrument, side, round(price, 2))
        if key in self._recent:
            logger.warning("Duplicate order detected: %s %s @ %.2f", instrument, side, price)
            return True
        self._recent.add(key)
        return False


class PartialFillHandler:
    def __init__(self):
        self._partials: dict[str, dict[str, Any]] = {}

    def record_partial(
        self, order_id: str, filled_qty: int, total_qty: int
    ) -> None:
        self._partials[order_id] = {
            "filled_qty": filled_qty,
            "total_qty": total_qty,
            "remaining": total_qty - filled_qty,
        }
        logger.info(
            "Partial fill recorded: %s %d/%d (remaining=%d)",
            order_id,
            filled_qty,
            total_qty,
            total_qty - filled_qty,
        )

    def is_complete(self, order_id: str) -> bool:
        record = self._partials.get(order_id)
        if record is None:
            return True
        return record.get("remaining", 0) <= 0

    def get_remaining(self, order_id: str) -> int:
        record = self._partials.get(order_id)
        if record is None:
            return 0
        return record.get("remaining", 0)


class BrokerReconnector:
    def __init__(
        self,
        base_delay: float = _RECONNECT_BASE_DELAY,
        max_delay: float = _RECONNECT_MAX_DELAY,
    ):
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._disconnect_count: int = 0
        self._connected: bool = True

    def should_reconnect(self, attempt: int) -> bool:
        return attempt <= 10

    def get_delay(self, attempt: int) -> float:
        delay = self._base_delay * (2 ** (attempt - 1))
        return min(delay, self._max_delay)

    def record_disconnect(self) -> None:
        self._disconnect_count += 1
        self._connected = False
        logger.warning(
            "Broker disconnected (count=%d)", self._disconnect_count
        )

    def record_reconnect(self) -> None:
        self._connected = True
        logger.info("Broker reconnected after %d disconnects", self._disconnect_count)

    def is_connected(self) -> bool:
        return self._connected


__all__ = [
    "BrokerReconnector",
    "DuplicateOrderProtector",
    "PartialFillHandler",
    "StaleDataWatchdog",
]
