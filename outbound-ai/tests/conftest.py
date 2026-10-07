import os
import pytest

os.environ.setdefault("SERVICE_PROVIDER", "mock")
os.environ.setdefault("SHEETS_PROVIDER", "fixture")

from agent.sheets import FixtureSheet  # noqa: E402


@pytest.fixture
def sheet() -> FixtureSheet:
    return FixtureSheet.load()
