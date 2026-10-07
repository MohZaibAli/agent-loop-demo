import httpx
import pytest

from api.main import app


@pytest.fixture
async def client():
    app.state.sheet.reset()
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
    # key alone is not enough: provider must be retell
    assert (await client.get("/mode", headers={"X-Demo-Key": "s3cret"})).json()["mode"] == "MOCK"
    monkeypatch.setenv("SERVICE_PROVIDER", "retell")
    assert (await client.get("/mode", headers={"X-Demo-Key": "s3cret"})).json()["mode"] == "LIVE"


async def test_leads_and_pending_filter(client):
    assert (await client.get("/leads")).json()["count"] == 5
    assert (await client.get("/leads?pending=true")).json()["count"] == 3


async def test_index_and_config(client):
    assert (await client.get("/")).status_code == 200
    cfg = (await client.get("/config")).json()
    assert "{{first_name}}" in cfg["sms_template"]
