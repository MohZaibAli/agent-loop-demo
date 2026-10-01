"""Prove runs are isolated: run A writes a marker, run B cannot see it; then
three parallel runs get three distinct sandbox IDs. Uses SANDBOX_PROVIDER.

    SANDBOX_PROVIDER=e2b uv run python scripts/isolation_check.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.events import EventLog  # noqa: E402
from agent.loop import run_agent  # noqa: E402
from agent.providers import ScriptedProvider  # noqa: E402
from agent.sandbox import create_sandbox, sandbox_provider  # noqa: E402

FIXTURE = "scripted_isolation_run.json"


async def scripted_run(key: str) -> tuple[str, EventLog]:
    log = EventLog()
    result = await run_agent(key, ScriptedProvider.from_fixture(FIXTURE, key), create_sandbox, log)
    return result.sandbox_id or "", log


async def main() -> int:
    print(f"sandbox provider: {sandbox_provider()}")
    sid_a, _ = await scripted_run("run_a")
    print(f"run A wrote marker in {sid_a}")
    sid_b, log_b = await scripted_run("run_b")
    results = [e.data["result"] for e in log_b.events if e.type == "tool_result"]
    marker_seen = "ISOLATION_MARKER" in results[0].get("stdout", "") or "error" not in results[1]
    print(f"run B ({sid_b}) marker visible: {marker_seen}")

    trio = await asyncio.gather(*[scripted_run("run_a") for _ in range(3)])
    ids = [sid for sid, _ in trio]
    print(f"parallel sandbox ids: {json.dumps(ids)}")
    ok = not marker_seen and sid_a != sid_b and len(set(ids)) == 3
    print("ISOLATION OK" if ok else "ISOLATION FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
