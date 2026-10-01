"""Phase 4: real E2B sandboxes. Marked `e2b`; skipped without E2B_API_KEY.
Only ScriptedProvider is used, so no LLM call is ever made here."""

import asyncio
import os

import pytest

from agent.events import EventLog
from agent.loop import run_agent
from agent.providers import ScriptedProvider
from agent.sandbox import E2B_TEMPLATE, WORKSPACE, E2BSandbox

pytestmark = [pytest.mark.e2b,
              pytest.mark.skipif(not os.environ.get("E2B_API_KEY"), reason="E2B_API_KEY not set")]


async def test_template_exists_and_has_tooling():
    from e2b import AsyncTemplate

    assert await AsyncTemplate.alias_exists(E2B_TEMPLATE) or await AsyncTemplate.exists(E2B_TEMPLATE)
    sb = await E2BSandbox.create(seed_dir=None, ttl_s=120)
    try:
        assert sb.sandbox_id
        py = await sb.run("python --version")
        assert "3.12" in py.stdout
        assert (await sb.run("command -v rg && python -m pytest --version")).exit_code == 0
        assert (await sb.run("curl -sS -m 5 https://example.com")).exit_code != 0  # no internet
    finally:
        await sb.kill()
    assert not await sb._sb.is_running()


async def test_seeded_repo_and_confinement():
    sb = await E2BSandbox.create(ttl_s=120)
    try:
        assert await sb.exists("listing_parser/parser.py")
        res = await sb.run("python -m pytest -q")
        assert "2 failed, 6 passed" in res.stdout
        assert (await sb.run("pwd")).stdout.strip() == WORKSPACE
        with pytest.raises(Exception):
            await sb.read_text("../../etc/passwd")
    finally:
        await sb.kill()


async def test_scripted_fix_reaches_eight_of_eight():
    log = EventLog()
    result = await run_agent("Fix the parser so all tests pass", ScriptedProvider.from_fixture(),
                             lambda: E2BSandbox.create(ttl_s=300), log)
    assert result.status == "complete"
    assert (result.tests_passed, result.tests_failed) == (8, 0)
    assert result.sandbox_id and not result.sandbox_id.startswith("local_")


async def test_isolation_and_three_concurrent_sandboxes():
    created: list[E2BSandbox] = []

    async def factory():
        sb = await E2BSandbox.create(ttl_s=300)
        created.append(sb)
        return sb

    await run_agent("a", ScriptedProvider.from_fixture("scripted_isolation_run.json", "run_a"), factory, EventLog())
    log_b = EventLog()
    await run_agent("b", ScriptedProvider.from_fixture("scripted_isolation_run.json", "run_b"), factory, log_b)
    read = [e for e in log_b.events if e.type == "tool_result" and e.data["name"] == "read_file"][0]
    assert "file not found" in read.data["result"]["error"]

    results = await asyncio.gather(*[
        run_agent("p", ScriptedProvider.from_fixture("scripted_isolation_run.json", "run_a"), factory, EventLog())
        for _ in range(3)])
    ids = {r.sandbox_id for r in results}
    assert len(ids) == 3
    # Cleanup: every sandbox is dead after its run.
    for sb in created:
        assert sb.alive is False
        assert not await sb._sb.is_running()
