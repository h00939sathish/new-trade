import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger("utils.retry")

async def with_retry(
    fn: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (httpx.HTTPError, httpx.TimeoutException, ConnectionError, OSError),
) -> Any:
    """Retries an async or sync function using exponential backoff."""
    for attempt in range(max_retries):
        try:
            res = fn()
            if asyncio.iscoroutine(res):
                return await res
            return res
        except exceptions as e:
            if attempt == max_retries - 1:
                logger.error("All %d retries failed: %s", max_retries, e)
                raise e
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning(
                "Retry %d/%d after %.1fs due to: %s",
                attempt + 1, max_retries, delay, e
            )
            await asyncio.sleep(delay)
