"""Retell AI outbound call: real httpx client and a deterministic mock."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

import httpx

from agent.fixtures import load_scripted_run, render

RETELL_API = "https://api.retellai.com"
CREATE_CALL = f"{RETELL_API}/v2/create-phone-call"


def call_payload(from_number: str, to_number: str, agent_id: str, variables: dict[str, str]) -> dict[str, Any]:
    return {
        "from_number": from_number,
        "to_number": to_number,
        "call_type": "phone_call",
        "agent_id": agent_id,
        "retell_llm_dynamic_variables": dict(variables),
    }


@dataclass
class CallResult:
    call_id: str
    call_status: str
    agent_id: str
    to: str
    from_: str
    request: dict[str, Any]
    response: dict[str, Any]
    mock: bool

    def to_dict(self) -> dict[str, Any]:
        return {"call_id": self.call_id, "call_status": self.call_status, "agent_id": self.agent_id,
                "to": self.to, "from": self.from_, "request": self.request, "response": self.response,
                "mock": self.mock}


class MockRetellClient:
    name = "mock"

    def __init__(self) -> None:
        self.calls: list[CallResult] = []
        self.agent_id = os.environ.get("RETELL_AGENT_ID") or "agent_mock_sarah"
        self.from_number = os.environ.get("RETELL_FROM_NUMBER") or "+10000000000"

    async def create_call(self, to: str, variables: dict[str, str]) -> CallResult:
        fx = load_scripted_run()["call"]
        digest = hashlib.sha1(f"{to}:{variables.get('first_name', '')}".encode()).hexdigest()[:16]
        call_id = f"{fx['call_id_prefix']}_{digest}"
        request = call_payload(self.from_number, to, self.agent_id, variables)
        response = {
            "call_id": call_id, "call_type": "phone_call", "agent_id": self.agent_id,
            "call_status": fx["call_status"], "from_number": self.from_number, "to_number": to,
            "direction": "outbound", "retell_llm_dynamic_variables": dict(variables),
            "metadata": {"mock": True, "transcript_preview": render(fx["transcript_preview"], variables)},
        }
        result = CallResult(call_id=call_id, call_status=fx["call_status"], agent_id=self.agent_id, to=to,
                            from_=self.from_number, request=request, response=response, mock=True)
        self.calls.append(result)
        return result


class RetellClient:
    """POST https://api.retellai.com/v2/create-phone-call with a Bearer token."""

    name = "retell"

    def __init__(self, api_key: str | None = None, agent_id: str | None = None,
                 from_number: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key or os.environ["RETELL_API_KEY"]
        self.agent_id = agent_id or os.environ["RETELL_AGENT_ID"]
        self.from_number = from_number or os.environ["RETELL_FROM_NUMBER"]
        self._client = client

    async def create_call(self, to: str, variables: dict[str, str]) -> CallResult:
        request = call_payload(self.from_number, to, self.agent_id, variables)
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            r = await client.post(CREATE_CALL, json=request,
                                  headers={"Authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()
            response = r.json()
        finally:
            if self._client is None:
                await client.aclose()
        return CallResult(call_id=response["call_id"], call_status=response.get("call_status", "registered"),
                          agent_id=self.agent_id, to=to, from_=self.from_number, request=request,
                          response=response, mock=False)
