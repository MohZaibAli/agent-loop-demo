"""Voice Flow Agent API: runs, batch runs, SSE event streams, budget, sheet views."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agent.budget import Budget
from agent.config import load_config, real_runs_allowed, service_provider
from agent.providers import real_configured, resolve_providers
from agent.registry import Registry, Run
from agent.sheets import filter_pending, make_sheet
from agent.workflow import run_workflow, wait_seconds

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Voice Flow Agent", version="0.2.0")
app.state.sheet = make_sheet()
app.state.budget = Budget()
app.state.registry = Registry()
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class RunRequest(BaseModel):
    lead_row: int | None = Field(default=None, ge=2)
    max_leads: int | None = Field(default=None, ge=1, le=25)
    wait_seconds: float | None = Field(default=None, ge=0, le=3600)


class LeadRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    phone: str = Field(min_length=7, max_length=20)
    job_title: str = Field(default="Registered Nurse", max_length=80)
    current_job_description: str = Field(default="Currently exploring new nursing roles.", max_length=300)
    new_job_opportunity: str = Field(default="Travel RN contract, 13 weeks, housing stipend included.", max_length=300)


class BatchRequest(BaseModel):
    count: int = Field(default=3, ge=1, le=3)
    lead_rows: list[int] | None = None
    wait_seconds: float | None = Field(default=None, ge=0, le=3600)


def _mode(x_demo_key: str | None) -> str:
    return "LIVE" if real_runs_allowed(x_demo_key) and real_configured() else "MOCK"


def _start(request: Request, body: RunRequest, demo_key: str | None) -> Run:
    providers = resolve_providers(demo_key)
    registry: Registry = request.app.state.registry
    run = registry.create("MOCK" if providers.mock else "LIVE", lead_row=body.lead_row)
    wait_s = body.wait_seconds if (body.wait_seconds is not None and providers.mock) else None

    async def execute() -> None:
        async with registry.semaphore:
            run.result = await run_workflow(
                request.app.state.sheet, providers, run.events, request.app.state.budget,
                run_id=run.id, max_leads=body.max_leads, lead_row=body.lead_row, wait_s=wait_s)

    run.task = asyncio.create_task(execute())
    return run


@app.post("/runs")
async def create_run(request: Request, body: RunRequest | None = None, wait: bool = False,
                     x_demo_key: str | None = Header(default=None)) -> dict[str, Any]:
    run = _start(request, body or RunRequest(), x_demo_key)
    if not wait:
        return {"run_id": run.id, "mode": run.mode}
    await asyncio.shield(run.task)
    return {"run_id": run.id, "mode": run.mode, **run.result.to_dict()}


@app.post("/runs/batch")
async def create_batch(request: Request, body: BatchRequest | None = None,
                       x_demo_key: str | None = Header(default=None)) -> dict[str, Any]:
    body = body or BatchRequest()
    rows = body.lead_rows
    if rows is None:
        pending = filter_pending(request.app.state.sheet.read_leads())
        rows = [l.row for l in pending[:body.count]]
        if len(rows) < body.count:
            raise HTTPException(409, f"only {len(rows)} pending leads; batch needs {body.count}")
    runs = [_start(request, RunRequest(lead_row=r, wait_seconds=body.wait_seconds), x_demo_key) for r in rows[:body.count]]
    return {"run_ids": [r.id for r in runs], "lead_rows": rows[:body.count], "mode": runs[0].mode}


@app.get("/runs")
async def list_runs(request: Request) -> list[dict[str, Any]]:
    return [r.to_dict() for r in request.app.state.registry.runs.values()]


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

    async def gen():
        async for ev in run.events.stream():
            yield {"id": str(ev.seq), "event": ev.type, "data": json.dumps(ev.to_dict())}

    return EventSourceResponse(gen())


@app.get("/budget")
async def budget(request: Request) -> dict[str, Any]:
    return request.app.state.budget.snapshot()


@app.get("/health")
def health():
    return {"ok": True, "provider": service_provider(), "sheet": app.state.sheet.name}


@app.get("/mode")
def mode(x_demo_key: str | None = Header(default=None)):
    return {"mode": _mode(x_demo_key), "provider": service_provider(), "sheet": app.state.sheet.name,
            "real_configured": real_configured(), "retell_agent_id": os.environ.get("RETELL_AGENT_ID") or "agent_mock_sarah",
            "wait_seconds": wait_seconds(_mode(x_demo_key) == "MOCK")}


@app.get("/leads")
def leads(pending: bool = False):
    rows = app.state.sheet.read_leads()
    if pending:
        rows = filter_pending(rows)
    return {"count": len(rows), "leads": [lead.to_dict() for lead in rows]}


@app.post("/leads")
def add_lead(body: LeadRequest):
    """Self-service lead: add a row to the sheet (Call Made empty) and return it."""
    phone = "".join(ch for ch in body.phone if ch.isdigit() or ch == "+")
    if not phone.startswith("+"):
        phone = "+" + phone
    from agent.sheets import COLUMNS
    record = dict(zip(COLUMNS, [phone, body.first_name.strip(), body.job_title, body.current_job_description,
                                body.new_job_opportunity, "", ""]))
    lead = app.state.sheet.add_lead(record)
    return lead.to_dict()


@app.post("/leads/reset")
def reset_leads():
    """Mock only: reload the fixture so the demo can be replayed."""
    sheet = app.state.sheet
    if not hasattr(sheet, "reset"):
        raise HTTPException(409, "reset is only available for the fixture sheet")
    sheet.reset()
    return {"count": len(filter_pending(sheet.read_leads()))}


@app.get("/config")
def config():
    cfg = load_config()
    return {"sms_template": cfg["sms_template"], "columns": cfg["sheet"]["columns"], "defaults": cfg["defaults"],
            "costs": cfg["costs"]}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
