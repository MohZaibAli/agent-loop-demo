from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def service_provider() -> str:
    return os.environ.get("SERVICE_PROVIDER", "mock").lower()


REAL_PROVIDERS = {"retell", "twilio"}


def real_runs_allowed(demo_key_header: str | None) -> bool:
    """Real runs need SERVICE_PROVIDER in {retell, twilio} AND a matching X-Demo-Key. Otherwise mock."""
    expected = os.environ.get("DEMO_KEY", "")
    return service_provider() in REAL_PROVIDERS and bool(expected) and demo_key_header == expected
