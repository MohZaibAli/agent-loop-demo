"""Ordered, replayable per-run event log with live subscribers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

TERMINAL = {"run_finished", "error"}


@dataclass
class Event:
    seq: int
    type: str
    ts: float
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "type": self.type, "ts": self.ts, **self.data}


@dataclass
class EventLog:
    events: list[Event] = field(default_factory=list)
    _subscribers: list[asyncio.Queue[Event | None]] = field(default_factory=list)
    done: bool = False

    def emit(self, type: str, **data: Any) -> Event:
        event = Event(seq=len(self.events), type=type, ts=time.time(), data=data)
        self.events.append(event)
        for queue in self._subscribers:
            queue.put_nowait(event)
        if type in TERMINAL:
            self.done = True
            for queue in self._subscribers:
                queue.put_nowait(None)
        return event

    async def stream(self) -> AsyncIterator[Event]:
        """Replay history, then yield new events until the run finishes."""
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            for event in list(self.events):
                yield event
            if self.done:
                return
            replayed = len(self.events)
            while True:
                event = await queue.get()
                if event is None:
                    return
                if event.seq < replayed:
                    continue  # already replayed from history
                yield event
        finally:
            self._subscribers.remove(queue)
