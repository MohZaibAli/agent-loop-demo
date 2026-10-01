"""Spin up the API on a free port with mock provider + local sandbox."""

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SCREENSHOTS = ROOT / "tests" / "e2e" / "screenshots"
CHROMIUM = "/opt/pw-browsers/chromium"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    port = _free_port()
    env = {**os.environ, "LLM_PROVIDER": "mock", "SANDBOX_PROVIDER": "local",
           "SPEND_FILE": str(tmp_path_factory.mktemp("spend") / "spend.json")}
    env.pop("OPENROUTER_API_KEY", None)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(port),
                             "--host", "127.0.0.1", "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/status", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("server did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        kwargs = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        b = p.chromium.launch(**kwargs)
        yield b
        b.close()


@pytest.fixture
def context(browser, request):
    reduced = "reduced_motion" in request.keywords
    ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                              reduced_motion="reduce" if reduced else "no-preference")
    yield ctx
    ctx.close()


@pytest.fixture
def page(context):
    page = context.new_page()
    # Google Fonts is not reachable from CI/sandboxed networks; serve an empty stylesheet
    # so font loading never counts as a page error. The real page still loads them.
    page.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"),
               lambda route: route.fulfill(status=200, content_type="text/css", body=""))
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.console_errors = errors
    yield page


def pytest_configure(config):
    config.addinivalue_line("markers", "reduced_motion: emulate prefers-reduced-motion")
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
