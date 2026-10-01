"""In-memory run registry: concurrency semaphore and sandbox reaper."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agent.events import EventLog
from agent.loop import RunResult
from agent.sandbox import Sandbox


@dataclass
class Run:
    id: str
    task: str
    provider: str
    scenario: str = "listing_parser"
    created_at: float = field(default_factory=time.time)
    events: EventLog = field(default_factory=EventLog)
    result: RunResult | None = None
    sandbox: Sandbox | None = None
    sandbox_started: float = 0.0
    last_activity: float = 0.0
    task_handle: asyncio.Task | None = None

    @property
    def status(self) -> str:
        if self.result:
            return self.result.status
        return "running" if self.sandbox else "queued"

    def touch(self) -> None:
        self.last_activity = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.id, "task": self.task, "status": self.status, "provider": self.provider,
            "scenario": self.scenario,
            "created_at": self.created_at, "sandbox_id": self.sandbox.sandbox_id if self.sandbox else None,
            "events": len(self.events.events), **({"result": self.result.to_dict()} if self.result else {}),
        }


class Registry:
    def __init__(self, max_concurrent: int | None = None, ttl_s: float = 900, idle_s: float = 300) -> None:
        limit = max_concurrent or int(os.environ.get("MAX_CONCURRENT_RUNS", "3"))
        self.semaphore = asyncio.Semaphore(limit)
        self.runs: dict[str, Run] = {}
        self.ttl_s = ttl_s
        self.idle_s = idle_s
        self._reaper: asyncio.Task | None = None

    def create(self, task: str, provider: str) -> Run:
        run = Run(id=f"run_{uuid.uuid4().hex[:12]}", task=task, provider=provider)
        self.runs[run.id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    def sandbox_factory(self, run: Run, create: Callable[[], Awaitable[Sandbox]]) -> Callable[[], Awaitable[Sandbox]]:
        """Wrap sandbox creation so the registry can track and reap it."""

        async def factory() -> Sandbox:
            sandbox = await create()
            run.sandbox = sandbox
            run.sandbox_started = time.time()
            run.touch()
            return _Tracked(sandbox, run)

        return factory

    async def reap_once(self) -> list[str]:
        """Kill sandboxes past TTL or idle timeout; returns killed sandbox ids."""
        now = time.time()
        killed = []
        for run in self.runs.values():
            sb = run.sandbox
            if sb is None or run.result is not None or not getattr(sb, "alive", True):
                continue
            expired = now - run.sandbox_started > self.ttl_s or now - run.last_activity > self.idle_s
            if expired:
                await sb.kill()
                killed.append(sb.sandbox_id)
                if run.task_handle:
                    run.task_handle.cancel()
        return killed

    def start_reaper(self, interval_s: float = 15) -> None:
        async def loop() -> None:
            while True:
                await asyncio.sleep(interval_s)
                await self.reap_once()

        self._reaper = asyncio.create_task(loop())

    async def shutdown(self) -> None:
        if self._reaper:
            self._reaper.cancel()
        pending = [r.task_handle for r in self.runs.values() if r.task_handle and not r.task_handle.done()]
        for handle in pending:
            handle.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for run in self.runs.values():
            if run.sandbox is not None and getattr(run.sandbox, "alive", True):
                await run.sandbox.kill()


class _Tracked:
    """Sandbox proxy that records activity for the idle reaper."""

    def __init__(self, inner: Sandbox, run: Run) -> None:
        self._inner = inner
        self._run = run

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr) or name == "kill":
            return attr

        async def wrapped(*a: Any, **kw: Any) -> Any:
            self._run.touch()
            return await attr(*a, **kw)

        return wrapped
