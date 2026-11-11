"""In-process event bus fanning out to SSE subscribers. Events are also persisted."""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
from datetime import datetime, timezone
from typing import Any

from app.core.db import save
from app.domain.tables import EventRow

EVENT_TYPES = {
    "tool_call", "tool_result", "stage_started", "stage_completed", "finding",
    "gate_requested", "gate_decided", "alert", "ledger_append", "metric",
    "run_started", "run_completed", "benchmark", "monitor", "security", "info", "agent_step", "traffic", "promotion",
}


class EventBus:
    def __init__(self) -> None:
        self._subs: set[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = set()
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        self._recent: list[dict] = []

    def reset_counter(self, start: int = 1) -> None:
        self._counter = itertools.count(start)
        self._recent.clear()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        with self._lock:
            self._subs.add((q, asyncio.get_running_loop()))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = {s for s in self._subs if s[0] is not q}

    def recent(self, n: int = 200) -> list[dict]:
        return self._recent[-n:]

    def publish(self, type: str, summary: str, *, run_id: str = "", model_id: str = "",
                stage: str = "", agent: str = "", payload: dict[str, Any] | None = None) -> dict:
        assert type in EVENT_TYPES, type
        evt = {
            "id": f"evt_{next(self._counter):06d}",
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "run_id": run_id, "model_id": model_id, "stage": stage, "agent": agent,
            "type": type, "summary": summary, "payload": _jsonable(payload or {}),
        }
        try:
            save(EventRow(**evt))
        except Exception:  # id collision after restart: keep streaming anyway
            pass
        self._recent.append(evt)
        if len(self._recent) > 1000:
            self._recent = self._recent[-500:]
        with self._lock:
            subs = list(self._subs)
        for q, loop in subs:
            try:
                loop.call_soon_threadsafe(_put, q, evt)
            except RuntimeError:
                self.unsubscribe(q)
        return evt


def _put(q: asyncio.Queue, evt: dict) -> None:
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(evt)


def _jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=_default))


def _default(o: Any):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    return str(o)


bus = EventBus()
