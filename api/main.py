"""FastAPI service: start runs, stream events, report budget."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agent.budget import Budget
from agent.cost import load_config
from agent.loop import run_agent
from agent.providers import Provider, make_provider
from agent.registry import Registry, Run
from agent.sandbox import create_sandbox, sandbox_provider

STATIC = Path(__file__).resolve().parent / "static"
DEFAULTS = load_config()["defaults"]


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    max_turns: int = Field(default=DEFAULTS["max_turns"], ge=1, le=50)
    max_cost_usd: float = Field(default=DEFAULTS["max_cost_usd"], gt=0, le=1.0)


class BatchRequest(RunRequest):
    count: int = Field(default=3, ge=1, le=3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.registry = Registry(ttl_s=DEFAULTS["sandbox_ttl_s"], idle_s=DEFAULTS["sandbox_idle_s"])
    app.state.budget = Budget()
    app.state.registry.start_reaper()
    yield
    await app.state.registry.shutdown()


app = FastAPI(title="Sandbox Agents", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _demo_key_valid(request: Request) -> bool:
    expected = os.environ.get("DEMO_KEY")
    return bool(expected) and request.headers.get("X-Demo-Key") == expected


def resolve_provider(request: Request) -> Provider:
    """Pick the provider for one request.

    LLM_PROVIDER=mock (default): real only when OPENROUTER_API_KEY is set AND the
    demo key matches; anything else silently falls back to mock.
    LLM_PROVIDER=openrouter (explicit): the demo key is mandatory -> 403 without it.
    """
    forced = (os.environ.get("LLM_PROVIDER") or "mock").lower()
    valid = _demo_key_valid(request)
    if forced == "openrouter":
        if not valid:
            raise HTTPException(403, "X-Demo-Key required for real runs")
        return make_provider("openrouter")
    if valid and os.environ.get("OPENROUTER_API_KEY"):
        return make_provider("openrouter")
    return make_provider("mock")


def _start_run(app: FastAPI, body: RunRequest, provider: Provider) -> Run:
    registry: Registry = app.state.registry
    run = registry.create(body.task, provider.name)
    factory = registry.sandbox_factory(run, lambda: create_sandbox(ttl_s=DEFAULTS["sandbox_ttl_s"]))

    async def execute() -> None:
        async with registry.semaphore:
            run.result = await run_agent(
                body.task, provider, factory, run.events, app.state.budget,
                max_turns=body.max_turns, max_cost_usd=body.max_cost_usd,
                timeout_s=DEFAULTS["run_timeout_s"], run_id=run.id,
            )

    run.task_handle = asyncio.create_task(execute())
    return run


@app.post("/runs")
async def create_run(body: RunRequest, request: Request, wait: bool = False) -> dict[str, Any]:
    provider = resolve_provider(request)
    run = _start_run(request.app, body, provider)
    if not wait:
        return {"run_id": run.id, "provider": provider.name}
    await asyncio.shield(run.task_handle)
    return {"run_id": run.id, "provider": provider.name, **run.result.to_dict()}


@app.post("/runs/batch")
async def create_batch(body: BatchRequest, request: Request) -> dict[str, Any]:
    provider_name = resolve_provider(request).name
    runs = [_start_run(request.app, body, resolve_provider(request)) for _ in range(body.count)]
    return {"run_ids": [r.id for r in runs], "provider": provider_name}


@app.get("/runs")
async def list_runs(request: Request) -> list[dict[str, Any]]:
    registry: Registry = request.app.state.registry
    return [r.to_dict() for r in registry.runs.values()]


@app.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    run = request.app.state.registry.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run.to_dict()


@app.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> EventSourceResponse:
    run = request.app.state.registry.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")

    async def generator():
        async for event in run.events.stream():
            yield {"id": str(event.seq), "event": event.type, "data": _json(event.to_dict())}

    return EventSourceResponse(generator())


@app.get("/budget")
async def budget(request: Request) -> dict[str, Any]:
    snap = request.app.state.budget.snapshot()
    return {**snap, "ceiling": request.app.state.budget.ceiling}


@app.get("/status")
async def status() -> dict[str, Any]:
    return {
        "llm_provider": (os.environ.get("LLM_PROVIDER") or "mock").lower(),
        "real_available": bool(os.environ.get("OPENROUTER_API_KEY")) and bool(os.environ.get("DEMO_KEY")),
        "sandbox_provider": sandbox_provider(),
        "model": os.environ.get("AGENT_MODEL") or "anthropic/claude-haiku-4.5",
        "router": os.environ.get("MODEL_ROUTER", "typesafe/jev-router"),
        "max_concurrent_runs": int(os.environ.get("MAX_CONCURRENT_RUNS", "3")),
        "defaults": DEFAULTS,
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def _json(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data)
