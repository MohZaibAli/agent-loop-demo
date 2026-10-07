import json

import httpx
import pytest

from agent import providers as prov
from agent.retell import CREATE_CALL, MockRetellClient, RetellClient, call_payload
from agent.twilio_client import MockTwilioClient, TwilioClient, sms_body

VARS = {"first_name": "Amelia", "job_title": "RN", "current_job_description": "x", "new_job_opportunity": "y"}


def test_sms_body_interpolates_template():
    body = sms_body(VARS)
    assert body.startswith("Hi Amelia, I'm Sarah")
    assert "{{" not in body and "Six Flow Nursing" in body


async def test_mock_sms_never_hits_network():
    c = MockTwilioClient()
    r = await c.send_sms("+15550100001", VARS)
    assert r.mock and r.sid.startswith("SMmock") and r.status == "queued" and r.price_usd == 0.0
    assert c.sent == [r]


async def test_real_twilio_posts_form_with_basic_auth():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        seen["form"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(201, json={"sid": "SM123", "status": "queued", "price": "-0.0079"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tw = TwilioClient("AC1", "tok", "+10000000000", client=client)
    r = await tw.send_sms("+15550100001", VARS)
    assert seen["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json"
    assert seen["auth"].startswith("Basic ")
    assert seen["form"]["To"] == "+15550100001" and seen["form"]["Body"].startswith("Hi Amelia")
    assert r.sid == "SM123" and r.price_usd == 0.0079 and not r.mock


def test_call_payload_shape():
    p = call_payload("+1", "+2", "agent_x", VARS)
    assert p == {"from_number": "+1", "to_number": "+2", "call_type": "phone_call", "agent_id": "agent_x",
                 "retell_llm_dynamic_variables": VARS}


async def test_mock_retell_is_deterministic():
    a = await MockRetellClient().create_call("+15550100001", VARS)
    b = await MockRetellClient().create_call("+15550100001", VARS)
    assert a.call_id == b.call_id and a.call_id.startswith("call_mock_")
    assert a.mock and a.call_status == "registered"
    assert a.response["retell_llm_dynamic_variables"] == VARS
    assert "Amelia" in a.response["metadata"]["transcript_preview"]


async def test_real_retell_posts_json_with_bearer():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["json"] = json.loads(request.content)
        return httpx.Response(201, json={"call_id": "call_abc", "call_status": "registered"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rc = RetellClient("key", "agent_1", "+10000000000", client=client)
    r = await rc.create_call("+15550100001", VARS)
    assert seen["url"] == CREATE_CALL and seen["auth"] == "Bearer key"
    assert seen["json"]["retell_llm_dynamic_variables"] == VARS and seen["json"]["call_type"] == "phone_call"
    assert r.call_id == "call_abc" and not r.mock


@pytest.mark.parametrize("provider,key,creds,expected", [
    ("mock", "k", True, "mock"),
    ("retell", None, True, "mock"),
    ("retell", "wrong", True, "mock"),
    ("retell", "k", False, "mock"),
    ("retell", "k", True, "live"),
    ("twilio", "k", True, "live"),
])
def test_resolve_providers_fallback(monkeypatch, provider, key, creds, expected):
    monkeypatch.setenv("SERVICE_PROVIDER", provider)
    monkeypatch.setenv("DEMO_KEY", "k")
    for name in ("RETELL_API_KEY", "RETELL_AGENT_ID", "RETELL_FROM_NUMBER", "TWILIO_ACCOUNT_SID",
                 "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
        monkeypatch.setenv(name, "x" if creds else "")
    assert prov.resolve_providers(key).name == expected
