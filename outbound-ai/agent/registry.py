"""In-memory run registry with a concurrency semaphore."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent.events import EventLog
from agent.workflow import RunResult


@dataclass
class Run:
    id: str
    mode: str
    created_at: float = field(default_factory=time.time)
    events: EventLog = field(default_factory=EventLog)
    result: RunResult | None = None
    task: asyncio.Task | None = None
    lead_row: int | None = None

    @property
    def status(self) -> str:
        return self.result.status if self.result else "running"

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.id, "mode": self.mode, "status": self.status, "created_at": self.created_at,
                "lead_row": self.lead_row, "events": len(self.events.events),
                **({"result": self.result.to_dict()} if self.result else {})}


class Registry:
    def __init__(self, max_concurrent: int | None = None) -> None:
        self.semaphore = asyncio.Semaphore(max_concurrent or int(os.environ.get("MAX_CONCURRENT_RUNS", "3")))
        self.runs: dict[str, Run] = {}

    def create(self, mode: str, lead_row: int | None = None) -> Run:
        run = Run(id=f"run_{uuid.uuid4().hex[:12]}", mode=mode, lead_row=lead_row)
        self.runs[run.id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)
