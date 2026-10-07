"""Twilio outbound SMS: real httpx client and a mock that never touches the network."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from agent.config import load_config
from agent.fixtures import load_scripted_run, render

TWILIO_API = "https://api.twilio.com"


def sms_body(variables: dict[str, str]) -> str:
    return render(load_config()["sms_template"].strip(), variables)


@dataclass
class SmsResult:
    sid: str
    status: str
    to: str
    from_: str
    body: str
    price_usd: float
    mock: bool

    def to_dict(self) -> dict[str, Any]:
        return {"sid": self.sid, "status": self.status, "to": self.to, "from": self.from_,
                "body": self.body, "price_usd": self.price_usd, "mock": self.mock}


class MockTwilioClient:
    name = "mock"

    def __init__(self) -> None:
        self.sent: list[SmsResult] = []

    async def send_sms(self, to: str, variables: dict[str, str]) -> SmsResult:
        fx = load_scripted_run()["sms"]
        result = SmsResult(sid=f"{fx['sid_prefix']}{uuid.uuid4().hex[:24]}", status=fx["status"], to=to,
                           from_=os.environ.get("TWILIO_FROM_NUMBER") or "+10000000000",
                           body=sms_body(variables), price_usd=0.0, mock=True)
        self.sent.append(result)
        return result


class TwilioClient:
    """POST /2010-04-01/Accounts/{AccountSid}/Messages.json with basic auth."""

    name = "twilio"

    def __init__(self, account_sid: str | None = None, auth_token: str | None = None,
                 from_number: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.account_sid = account_sid or os.environ["TWILIO_ACCOUNT_SID"]
        self.auth_token = auth_token or os.environ["TWILIO_AUTH_TOKEN"]
        self.from_number = from_number or os.environ["TWILIO_FROM_NUMBER"]
        self._client = client

    async def send_sms(self, to: str, variables: dict[str, str]) -> SmsResult:
        body = sms_body(variables)
        url = f"{TWILIO_API}/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        data = {"To": to, "From": self.from_number, "Body": body}
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            r = await client.post(url, data=data, auth=(self.account_sid, self.auth_token))
            r.raise_for_status()
            payload = r.json()
        finally:
            if self._client is None:
                await client.aclose()
        price = abs(float(payload.get("price") or 0.0)) or float(load_config()["costs"]["sms_usd"])
        return SmsResult(sid=payload["sid"], status=payload.get("status", "queued"), to=to,
                         from_=self.from_number, body=body, price_usd=price, mock=False)
