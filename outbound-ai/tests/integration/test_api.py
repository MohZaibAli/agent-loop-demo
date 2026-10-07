import asyncio
import json

import httpx
import pytest

from api.main import app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    from agent.budget import Budget
    app.state.sheet.reset()
    app.state.budget = Budget(path=str(tmp_path / "spend.json"))
    monkeypatch.setenv("WAIT_SECONDS_MOCK", "0.02")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_health_is_mock(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["provider"] == "mock" and r.json()["sheet"] == "fixture"


async def test_mode_falls_back_to_mock_without_key(client, monkeypatch):
    monkeypatch.setenv("DEMO_KEY", "s3cret")
    assert (await client.get("/mode")).json()["mode"] == "MOCK"
    assert (await client.get("/mode", headers={"X-Demo-Key": "wrong"})).json()["mode"] == "MOCK"
    assert (await client.get("/mode", headers={"X-Demo-Key": "s3cret"})).json()["mode"] == "MOCK"
    monkeypatch.setenv("SERVICE_PROVIDER", "retell")
    # provider + key but no credentials: still mock
    assert (await client.get("/mode", headers={"X-Demo-Key": "s3cret"})).json()["mode"] == "MOCK"
    for k in ("RETELL_API_KEY", "RETELL_AGENT_ID", "RETELL_FROM_NUMBER", "TWILIO_ACCOUNT_SID",
              "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
        monkeypatch.setenv(k, "x")
    assert (await client.get("/mode", headers={"X-Demo-Key": "s3cret"})).json()["mode"] == "LIVE"


async def test_leads_pending_filter_and_reset(client):
    assert (await client.get("/leads")).json()["count"] == 5
    assert (await client.get("/leads?pending=true")).json()["count"] == 3
    assert (await client.post("/leads/reset")).json()["count"] == 3


async def test_run_wait_completes_all_steps(client):
    r = await client.post("/runs?wait=true", json={"lead_row": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "MOCK" and body["status"] == "completed" and body["leads_processed"] == 1
    assert body["cost_usd"] == 0.0
    run = (await client.get(f"/runs/{body['run_id']}")).json()
    assert run["status"] == "completed"
    assert (await client.get("/leads?pending=true")).json()["count"] == 2


async def test_sse_stream_has_all_six_steps(client):
    run_id = (await client.post("/runs", json={"lead_row": 3})).json()["run_id"]
    types, steps = [], []
    async with client.stream("GET", f"/runs/{run_id}/events") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                types.append(ev["type"]); steps.append(ev["step"])
                assert set(ev) == {"event_id", "seq", "timestamp", "type", "step", "data"}
                if ev["type"] == "run_finished":
                    break
    assert types[-1] == "run_finished"
    assert [s for t, s in zip(types, steps) if t == "step_complete"] == [
        "FETCH_SHEETS", "FILTER_LEADS", "SEND_SMS", "WAIT", "RETELL_CALL", "UPDATE_SHEET"]


async def test_batch_three_isolated_runs(client):
    r = await client.post("/runs/batch", json={"count": 3})
    assert r.status_code == 200
    ids = r.json()["run_ids"]
    assert len(set(ids)) == 3 and r.json()["lead_rows"] == [2, 3, 5]
    for _ in range(200):
        runs = {x["run_id"]: x for x in (await client.get("/runs")).json()}
        if all(runs[i]["status"] == "completed" for i in ids):
            break
        await asyncio.sleep(0.02)
    assert all(runs[i]["result"]["leads_processed"] == 1 for i in ids)
    assert (await client.get("/leads?pending=true")).json()["count"] == 0
    assert (await client.post("/runs/batch", json={"count": 3})).status_code == 409


async def test_budget_endpoint_and_zero_mock_spend(client):
    await client.post("/runs?wait=true")
    b = (await client.get("/budget")).json()
    assert b["spent"] == 0.0 and b["ceiling"] == 4.0 and b["remaining"] == 4.0


async def test_unknown_run_404(client):
    assert (await client.get("/runs/nope")).status_code == 404
    assert (await client.get("/runs/nope/events")).status_code == 404


async def test_index_and_config(client):
    assert (await client.get("/")).status_code == 200
    cfg = (await client.get("/config")).json()
    assert "{{first_name}}" in cfg["sms_template"]


async def test_add_lead_then_run_it(client):
    r = await client.post("/leads", json={"first_name": "Mo", "phone": "+1 (555) 010-0099"})
    assert r.status_code == 200 and r.json()["row"] == 7 and r.json()["phone"] == "+15550100099"
    res = (await client.post("/runs?wait=true", json={"lead_row": 7})).json()
    assert res["status"] == "completed" and res["calls"][0]["first_name"] == "Mo"
    assert (await client.post("/leads", json={"first_name": "", "phone": "1"})).status_code == 422
