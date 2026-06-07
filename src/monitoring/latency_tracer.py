import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("latency_tracer")


class LatencyTracer:
    def __init__(self, log_dir: str = "logs/runtime_traces"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"traces_{datetime.now(UTC).strftime('%Y%m%d')}.jsonl"

    def record_trace(
        self,
        correlation_id: str,
        component: str,
        latency_ms: float,
        extra: dict[str, Any] | None = None,
    ) -> None:
        try:
            if not correlation_id:
                return
            trace_data = {
                "correlation_id": correlation_id,
                "component": component,
                "latency_ms": round(latency_ms, 2),
                "recorded_at": datetime.now(UTC).isoformat(),
            }
            if extra:
                trace_data.update(extra)

            with open(self.log_file, "a") as f:
                f.write(json.dumps(trace_data) + "\n")
        except Exception as e:
            logger.error("Failed to record trace: %s", e)


tracer = LatencyTracer()
