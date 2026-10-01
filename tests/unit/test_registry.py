"""Phase 4 (local): registry concurrency and reaper, using LocalSandbox."""

import asyncio
import time
from pathlib import Path

from agent.events import EventLog
from agent.loop import run_agent
from agent.providers import ScriptedProvider
from agent.registry import Registry
from agent.sandbox import LocalSandbox, create_sandbox

SEED = str(Path(__file__).resolve().parents[2] / "seed_repo")


async def test_semaphore_limits_concurrency():
    reg = Registry(max_concurrent=2)
    active, peak = 0, 0

    async def job():
        nonlocal active, peak
        async with reg.semaphore:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*[job() for _ in range(6)])
    assert peak == 2


async def test_tracked_factory_records_sandbox_and_run_completes():
    reg = Registry(max_concurrent=3)
    run = reg.create("t", "mock")
    factory = reg.sandbox_factory(run, lambda: LocalSandbox.create(seed_dir=SEED))
    result = await run_agent("t", ScriptedProvider.from_fixture(), factory, run.events)
    run.result = result
    assert run.sandbox is not None and run.sandbox.sandbox_id == result.sandbox_id
    assert run.status == "complete" and run.to_dict()["result"]["tests_passed"] == 8
    assert run.last_activity > run.sandbox_started - 1


async def test_reaper_kills_idle_and_expired(monkeypatch):
    reg = Registry(max_concurrent=3, ttl_s=1000, idle_s=0.05)
    run = reg.create("t", "mock")
    sb = await reg.sandbox_factory(run, lambda: LocalSandbox.create(seed_dir=SEED))()
    assert await reg.reap_once() == []
    await asyncio.sleep(0.08)
    assert await reg.reap_once() == [sb.sandbox_id]
    assert run.sandbox.alive is False
    # TTL path
    run2 = reg.create("t2", "mock")
    sb2 = await reg.sandbox_factory(run2, lambda: LocalSandbox.create(seed_dir=SEED))()
    reg.idle_s = 1000
    run2.sandbox_started = time.time() - 2000
    assert await reg.reap_once() == [sb2.sandbox_id]


async def test_create_sandbox_respects_provider_env(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    sb = await create_sandbox(seed_dir=SEED)
    assert isinstance(sb, LocalSandbox) and await sb.exists("pytest.ini")
    await sb.kill()
