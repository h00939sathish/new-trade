import asyncio
import logging
import time

logger = logging.getLogger("execution.throttle")


class TokenBucket:
    """Token-bucket rate limiter.

    Allows up to `max_rate` operations per `window_seconds`, with burst
    of up to `max_rate` tokens initially. Tokens refill continuously.
    """

    def __init__(self, max_rate: int = 10, window_seconds: float = 1.0):
        self._max_rate = max_rate
        self._window_seconds = window_seconds
        self._tokens = float(max_rate)
        self._refill_rate = max_rate / window_seconds
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(float(self._max_rate), self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    async def acquire(self, tokens: float = 1.0) -> bool:
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    async def wait_and_acquire(self, tokens: float = 1.0, timeout: float | None = None) -> bool:
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            if await self.acquire(tokens):
                return True
            if deadline and time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)


class MultiKeyTokenBucket:
    """Token bucket with per-key and global limits.

    Useful for per-symbol rate limiting with a global cap.
    """

    def __init__(self, global_rate: int = 50, per_key_rate: int = 10, window_seconds: float = 1.0):
        self._global = TokenBucket(global_rate, window_seconds)
        self._per_key: dict[str, TokenBucket] = {}
        self._per_key_rate = per_key_rate
        self._window_seconds = window_seconds
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, tokens: float = 1.0) -> bool:
        async with self._lock:
            if key not in self._per_key:
                self._per_key[key] = TokenBucket(self._per_key_rate, self._window_seconds)
        if not await self._per_key[key].acquire(tokens):
            return False
        if not await self._global.acquire(tokens):
            return False
        return True

    async def wait_and_acquire(
        self, key: str, tokens: float = 1.0, timeout: float | None = None
    ) -> bool:
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            if await self.acquire(key, tokens):
                return True
            if deadline and time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)
