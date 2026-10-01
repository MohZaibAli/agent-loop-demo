"""FastAPI service: start runs, stream events, report budget."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
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
from agent.scenarios import DEFAULT_SCENARIO, SCENARIOS, BadUpload, extract_upload, list_scenarios, scenario_dir

STATIC = Path(__file__).resolve().parent / "static"
DEFAULTS = load_config()["defaults"]


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    scenario: str = DEFAULT_SCENARIO
    max_turns: int = Field(default=DEFAULTS["max_turns"], ge=1, le=50)
    max_cost_usd: float = Field(default=DEFAULTS["max_cost_usd"], gt=0, le=1.0)


class BatchRequest(RunRequest):
    count: int = Field(default=3, ge=1, le=3)


log = logging.getLogger("uvicorn.error")


async def _ensure_e2b_template() -> None:
    """One-time template build on first boot with an E2B key; never installs anything per run."""
    try:
        from scripts.build_e2b_template import ensure_template

        await ensure_template(log.info)
    except Exception as exc:  # noqa: BLE001 - startup must not die on a template problem
        log.error("E2B template check failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.registry = Registry(ttl_s=DEFAULTS["sandbox_ttl_s"], idle_s=DEFAULTS["sandbox_idle_s"])
    app.state.budget = Budget()
    app.state.registry.start_reaper()
    if sandbox_provider() == "e2b" and os.environ.get("E2B_API_KEY"):
        app.state.template_task = asyncio.create_task(_ensure_e2b_template())
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


def _workspace_for(body: RunRequest, provider: Provider, upload_dir: Path | None) -> Path:
    """Seed directory for the run; only the scripted scenario is replayable in mock mode."""
    if upload_dir is not None:
        if provider.name == "mock":
            raise HTTPException(400, "Uploaded repositories need the live model. Enter the demo key (press r twice).")
        return upload_dir
    if body.scenario not in SCENARIOS:
        raise HTTPException(422, f"unknown scenario: {body.scenario}")
    if provider.name == "mock" and not SCENARIOS[body.scenario]["mock"]:
        raise HTTPException(400, "This scenario needs the live model. Enter the demo key (press r twice).")
    return scenario_dir(body.scenario)


def _start_run(app: FastAPI, body: RunRequest, provider: Provider, upload_dir: Path | None = None) -> Run:
    registry: Registry = app.state.registry
    seed = _workspace_for(body, provider, upload_dir)
    run = registry.create(body.task, provider.name)
    run.scenario = "upload" if upload_dir else body.scenario
    factory = registry.sandbox_factory(
        run, lambda: create_sandbox(seed_dir=str(seed), ttl_s=DEFAULTS["sandbox_ttl_s"]))

    async def execute() -> None:
        try:
            async with registry.semaphore:
                run.result = await run_agent(
                    body.task, provider, factory, run.events, app.state.budget,
                    max_turns=body.max_turns, max_cost_usd=body.max_cost_usd,
                    timeout_s=DEFAULTS["run_timeout_s"], run_id=run.id,
                )
        finally:
            if upload_dir is not None:
                shutil.rmtree(upload_dir, ignore_errors=True)

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


@app.post("/runs/upload")
async def create_run_from_upload(
    request: Request,
    task: str = Form(min_length=1, max_length=4000),
    repo: UploadFile = File(...),
    max_turns: int = Form(default=DEFAULTS["max_turns"], ge=1, le=50),
    max_cost_usd: float = Form(default=DEFAULTS["max_cost_usd"], gt=0, le=1.0),
    wait: bool = False,
) -> dict[str, Any]:
    """Like POST /runs, but the workspace is the uploaded zip instead of a seed scenario."""
    provider = resolve_provider(request)
    try:
        upload_dir = extract_upload(await repo.read())
    except BadUpload as exc:
        raise HTTPException(400, str(exc)) from exc
    body = RunRequest(task=task, max_turns=max_turns, max_cost_usd=max_cost_usd)
    try:
        run = _start_run(request.app, body, provider, upload_dir)
    except HTTPException:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise
    if not wait:
        return {"run_id": run.id, "provider": provider.name}
    await asyncio.shield(run.task_handle)
    return {"run_id": run.id, "provider": provider.name, **run.result.to_dict()}


@app.get("/scenarios")
async def scenarios() -> list[dict[str, Any]]:
    return list_scenarios()


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
