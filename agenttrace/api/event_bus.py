"""Server-sent event publishing for the AgentTrace API."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def publish(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "type": event_type,
            "created_at": _utc_now(),
            **payload,
        }
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(event)
        return event

    def stream(self):
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
        try:
            yield _sse_frame({"type": "connected"}, event_type="connected")
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    yield _sse_frame(event, event_type=event["type"])
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with self._lock:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)


def _sse_frame(payload: dict[str, Any], *, event_type: str) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
