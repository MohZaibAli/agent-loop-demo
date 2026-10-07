"""Voice Flow Agent API. Phase 1: health, lead listing from the sheet layer, mode."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent.config import load_config, real_runs_allowed, service_provider
from agent.sheets import filter_pending, make_sheet

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Voice Flow Agent", version="0.1.0")
app.state.sheet = make_sheet()
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
def health():
    return {"ok": True, "provider": service_provider(), "sheet": app.state.sheet.name}


@app.get("/mode")
def mode(x_demo_key: str | None = Header(default=None)):
    return {"mode": "LIVE" if real_runs_allowed(x_demo_key) else "MOCK", "provider": service_provider()}


@app.get("/leads")
def leads(pending: bool = False):
    rows = app.state.sheet.read_leads()
    if pending:
        rows = filter_pending(rows)
    return {"count": len(rows), "leads": [lead.to_dict() for lead in rows]}


@app.get("/config")
def config():
    cfg = load_config()
    return {"sms_template": cfg["sms_template"], "columns": cfg["sheet"]["columns"], "defaults": cfg["defaults"]}


@app.get("/")
def index(request: Request):
    return FileResponse(STATIC / "index.html")
