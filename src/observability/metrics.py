from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True, frozen=True)
class MetricEvent:
    name: str
    timestamp: datetime
    tags: dict[str, Any]


class MetricsCollector:
    def __init__(self) -> None:
        self._events: list[MetricEvent] = []
        self._counters: Counter[str] = Counter()

    def record(self, name: str, **tags: Any) -> None:
        self._events.append(
            MetricEvent(name=name, timestamp=datetime.now(timezone.utc), tags=tags)
        )
        self._counters[name] += 1

    def events(self, name: str | None = None) -> list[MetricEvent]:
        if name is None:
            return list(self._events)
        return [event for event in self._events if event.name == name]

    def counter(self, name: str) -> int:
        return self._counters[name]
