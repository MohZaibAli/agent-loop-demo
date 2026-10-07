"""Mock vs real provider selection. Real only with SERVICE_PROVIDER in {retell,twilio} AND a valid key."""
from __future__ import annotations

import os
from dataclasses import dataclass

from agent.config import REAL_PROVIDERS, real_runs_allowed, service_provider
from agent.retell import MockRetellClient, RetellClient
from agent.twilio_client import MockTwilioClient, TwilioClient



@dataclass
class Providers:
    name: str  # "mock" | "live"
    sms: MockTwilioClient | TwilioClient
    calls: MockRetellClient | RetellClient

    @property
    def mock(self) -> bool:
        return self.name == "mock"


def real_configured() -> bool:
    return all(os.environ.get(k) for k in ("RETELL_API_KEY", "RETELL_AGENT_ID", "RETELL_FROM_NUMBER",
                                            "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))


def resolve_providers(demo_key: str | None) -> Providers:
    """Fall back to mock unless provider is real, the demo key matches and credentials exist."""
    if service_provider() in REAL_PROVIDERS and real_runs_allowed(demo_key) and real_configured():
        return Providers(name="live", sms=TwilioClient(), calls=RetellClient())
    return Providers(name="mock", sms=MockTwilioClient(), calls=MockRetellClient())
