"""Phase 5: API, SSE, budget and demo-key protection. Mock provider, local sandbox."""

import asyncio
import json
import os

import httpx
import pytest
from asgi_lifespan import LifespanManager

from api.main import app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEND_FILE", str(tmp_path / "spend.json"))
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DEMO_KEY", raising=False)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
            yield c


async def read_sse(client: httpx.AsyncClient, run_id: str) -> list[dict]:
    events = []
    async with client.stream("GET", f"/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


async def test_post_runs_starts_async(client):
    r = await client.post("/runs", json={"task": "Fix the parser so all tests pass"})
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"].startswith("run_") and body["provider"] == "mock"
    r = await client.get(f"/runs/{body['run_id']}")
    assert r.json()["status"] in {"queued", "running", "complete"}


async def test_wait_mode_returns_final_result(client):
    r = await client.post("/runs?wait=true", json={"task": "Fix the parser so all tests pass"})
    body = r.json()
    assert body["status"] == "complete"
    assert (body["tests_passed"], body["tests_failed"]) == (8, 0)
    assert body["turns"] == 7 and body["cost"] == 0
    assert "amount *= 1000" in body["diff"]


async def test_validation(client):
    assert (await client.post("/runs", json={})).status_code == 422
    assert (await client.post("/runs", json={"task": "x", "max_cost_usd": 5})).status_code == 422
    assert (await client.get("/runs/nope")).status_code == 404
    assert (await client.get("/runs/nope/events")).status_code == 404


async def test_sse_replays_history_after_completion(client):
    run_id = (await client.post("/runs?wait=true", json={"task": "t"})).json()["run_id"]
    events = await read_sse(client, run_id)
    assert events[0]["type"] == "run_started" and events[-1]["type"] == "run_finished"
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert sum(e["type"] == "tool_call" for e in events) == 6


async def test_sse_streams_live_events_in_order(client):
    run_id = (await client.post("/runs", json={"task": "t"})).json()["run_id"]
    events = await read_sse(client, run_id)
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert events[-1]["type"] == "run_finished" and events[-1]["tests_passed"] == 8
    # A second subscriber after completion gets the identical replay.
    assert await read_sse(client, run_id) == events


async def test_list_runs(client):
    await client.post("/runs?wait=true", json={"task": "listed"})
    runs = (await client.get("/runs")).json()
    assert any(r["task"] == "listed" and r["status"] == "complete" for r in runs)


async def test_budget_endpoint_never_exceeds_ceiling(client):
    body = (await client.get("/budget")).json()
    assert body == {"spent": 0.0, "remaining": 4.0, "ceiling": 4.0}
    from agent.budget import Budget
    Budget(os.environ["SPEND_FILE"]).add(0.018)
    body = (await client.get("/budget")).json()
    assert body["spent"] == 0.018 and body["remaining"] == 3.982
    Budget(os.environ["SPEND_FILE"]).add(10)
    assert (await client.get("/budget")).json()["remaining"] == 0.0


async def test_forced_openrouter_requires_demo_key(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("DEMO_KEY", "secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake")
    assert (await client.post("/runs", json={"task": "t"})).status_code == 403
    r = await client.post("/runs", json={"task": "t"}, headers={"X-Demo-Key": "wrong"})
    assert r.status_code == 403
    # Correct key selects the real provider (no request is sent until the loop runs;
    # the fake key makes the provider fail fast with an error event, never a mock swap).
    r = await client.post("/runs?wait=true", json={"task": "t"}, headers={"X-Demo-Key": "secret"})
    assert r.status_code == 200 and r.json()["provider"] == "openrouter"
    assert r.json()["status"] == "error"


async def test_default_mode_falls_back_to_mock_without_valid_key(client, monkeypatch):
    monkeypatch.setenv("DEMO_KEY", "secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake")
    for headers in ({}, {"X-Demo-Key": "wrong"}):
        r = await client.post("/runs", json={"task": "t"}, headers=headers)
        assert r.status_code == 200 and r.json()["provider"] == "mock"
    r = await client.post("/runs", json={"task": "t"}, headers={"X-Demo-Key": "secret"})
    assert r.json()["provider"] == "openrouter"


async def test_mock_default_without_api_key_ignores_demo_key(client, monkeypatch):
    monkeypatch.setenv("DEMO_KEY", "secret")
    r = await client.post("/runs", json={"task": "t"}, headers={"X-Demo-Key": "secret"})
    assert r.json()["provider"] == "mock"


async def test_batch_max_three_distinct_sandboxes(client):
    assert (await client.post("/runs/batch", json={"task": "t", "count": 4})).status_code == 422
    r = await client.post("/runs/batch", json={"task": "t", "count": 3})
    ids = r.json()["run_ids"]
    assert len(ids) == 3
    results = await asyncio.gather(*[read_sse(client, i) for i in ids])
    sandbox_ids = {ev[0]["sandbox_id"] for ev in results}
    assert len(sandbox_ids) == 3
    assert all(ev[-1]["tests_passed"] == 8 for ev in results)


async def test_status_endpoint(client):
    body = (await client.get("/status")).json()
    assert body["llm_provider"] == "mock" and body["sandbox_provider"] == "local"
    assert body["real_available"] is False


# --- scenarios -----------------------------------------------------------------

async def test_scenarios_endpoint(client):
    body = (await client.get("/scenarios")).json()
    assert [s["id"] for s in body] == ["listing_parser", "invoice_engine", "log_pipeline"]
    assert [s["mock"] for s in body] == [True, False, False]


async def test_mock_gates_live_scenarios_with_403(client):
    r = await client.post("/runs", json={"task": "t", "scenario": "invoice_engine"})
    assert r.status_code == 403 and "demo password" in r.json()["detail"]
    r = await client.post("/runs/batch", json={"task": "t", "scenario": "log_pipeline", "count": 2})
    assert r.status_code == 403
    assert (await client.post("/runs", json={"task": "t", "scenario": "nope"})).status_code == 422


async def test_live_scenario_starts_with_real_provider(client, monkeypatch):
    monkeypatch.setenv("DEMO_KEY", "secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake")
    r = await client.post("/runs?wait=true", json={"task": "t", "scenario": "invoice_engine"},
                          headers={"X-Demo-Key": "secret"})
    assert r.status_code == 200 and r.json()["provider"] == "openrouter"
    assert r.json()["status"] == "error"  # fake key: provider fails, workspace was still prepared
    assert (await client.get(f"/runs/{r.json()['run_id']}")).json()["scenario"] == "invoice_engine"
    # Wrong password on a live scenario is a 403, never a silent mock run.
    r = await client.post("/runs", json={"task": "t", "scenario": "invoice_engine"}, headers={"X-Demo-Key": "nope"})
    assert r.status_code == 403
