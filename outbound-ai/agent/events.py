"""Ordered, replayable per-run event log streamed over SSE.

Every event has the standard shape:
{ "event_id", "seq", "timestamp", "type", "step", "data" }
type is one of step_start | step_payload | step_complete | step_error | run_finished.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from agent.sheets import now_iso

TERMINAL = {"run_finished"}
STEPS = ["FETCH_SHEETS", "FILTER_LEADS", "SEND_SMS", "WAIT", "RETELL_CALL", "UPDATE_SHEET"]


@dataclass
class Event:
    seq: int
    type: str
    step: str | None
    timestamp: str
    data: dict[str, Any]
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:10]}")

    def to_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "seq": self.seq, "timestamp": self.timestamp,
                "type": self.type, "step": self.step, "data": self.data}


@dataclass
class EventLog:
    events: list[Event] = field(default_factory=list)
    done: bool = False
    _subscribers: list[asyncio.Queue] = field(default_factory=list)

    def emit(self, type: str, step: str | None = None, **data: Any) -> Event:
        ev = Event(seq=len(self.events), type=type, step=step, timestamp=now_iso(), data=data)
        self.events.append(ev)
        for q in self._subscribers:
            q.put_nowait(ev)
        if type in TERMINAL:
            self.done = True
            for q in self._subscribers:
                q.put_nowait(None)
        return ev

    async def stream(self) -> AsyncIterator[Event]:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        try:
            replayed = len(self.events)
            for ev in list(self.events):
                yield ev
            if self.done:
                return
            while True:
                ev = await q.get()
                if ev is None:
                    return
                if ev.seq < replayed:
                    continue
                yield ev
        finally:
            self._subscribers.remove(q)
