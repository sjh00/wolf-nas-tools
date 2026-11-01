"""元数据链路轻量指标（进程内）."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class _Metrics:
    provider_success: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    provider_failure: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    provider_latency_ms: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    snapshots: int = 0
    conflicts: int = 0
    degraded: int = 0
    events: deque = field(default_factory=lambda: deque(maxlen=200))
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "provider_success": dict(self.provider_success),
                "provider_failure": dict(self.provider_failure),
                "provider_latency_ms": dict(self.provider_latency_ms),
                "snapshots": self.snapshots,
                "conflicts": self.conflicts,
                "degraded": self.degraded,
                "events": list(self.events),
            }


metrics = _Metrics()


def record_provider_result(provider: str, *, ok: bool, latency_ms: int) -> None:
    with metrics.lock:
        target = metrics.provider_success if ok else metrics.provider_failure
        target[provider] += 1
        metrics.provider_latency_ms[provider] = latency_ms


def record_snapshot(conflicts: int = 0) -> None:
    with metrics.lock:
        metrics.snapshots += 1
        metrics.conflicts += max(0, conflicts)


def record_degraded() -> None:
    with metrics.lock:
        metrics.degraded += 1
        metrics.events.append({"ts": time.time(), "event": "metadata.degraded"})


def record_event(event: str, **payload) -> None:
    with metrics.lock:
        metrics.events.append({"ts": time.time(), "event": event, **payload})


def snapshot() -> dict:
    return metrics.snapshot()
