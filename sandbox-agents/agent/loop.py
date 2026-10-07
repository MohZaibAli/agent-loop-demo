"""The agent loop: provider turn -> tool execution -> repeat until done."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agent.budget import Budget
from agent.cost import Usage
from agent.events import EventLog
from agent.providers import Provider
from agent.sandbox import Sandbox
from agent.tools import TOOL_SCHEMAS, run_tool

SYSTEM_PROMPT = """You are a coding agent operating inside /home/user/workspace.

Inspect the repository, make the smallest correct changes required by the task, and always verify your work by running the relevant tests.

Do not modify files outside the workspace.

Continue until the task is complete and verified."""

PYTEST_SUMMARY = re.compile(r"(?:(\d+) failed, )?(\d+) passed")
SandboxFactory = Callable[[], Awaitable[Sandbox]]


@dataclass
class RunResult:
    status: str
    summary: str
    tests_passed: int | None
    tests_failed: int | None
    turns: int
    usage: Usage
    sandbox_id: str | None
    model: str
    provider: str
    diff: str = ""
    routed_model: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "summary": self.summary,
            "tests_passed": self.tests_passed, "tests_failed": self.tests_failed,
            "turns": self.turns, "tokens": self.usage.total_tokens, "cost": round(self.usage.cost, 6),
            "usage": self.usage.to_dict(), "sandbox_id": self.sandbox_id,
            "model": self.model, "routed_model": self.routed_model or self.model,
            "provider": self.provider, "diff": self.diff,
        }


def parse_pytest(stdout: str) -> tuple[int, int] | None:
    match = PYTEST_SUMMARY.search(stdout)
    if not match:
        return None
    return int(match.group(2)), int(match.group(1) or 0)


async def run_agent(
    task: str,
    provider: Provider,
    sandbox_factory: SandboxFactory,
    events: EventLog,
    budget: Budget | None = None,
    max_turns: int = 15,
    max_cost_usd: float = 0.25,
    timeout_s: float = 600,
    run_id: str = "",
) -> RunResult:
    usage = Usage()
    tests: tuple[int, int] | None = None
    diffs: list[str] = []
    turns = 0
    routed_model = ""
    sandbox: Sandbox | None = None
    is_real = provider.name != "mock"
    started = time.monotonic()

    def finish(status: str, summary: str) -> RunResult:
        result = RunResult(status, summary, tests[0] if tests else None, tests[1] if tests else None,
                           turns, usage, sandbox.sandbox_id if sandbox else None,
                           provider.model, provider.name, "\n".join(diffs), routed_model)
        events.emit("run_finished", **result.to_dict())
        result.events = [e.to_dict() for e in events.events]
        return result

    if is_real and budget is not None:
        ok, reason = budget.can_start(max_cost_usd)
        if not ok:
            events.emit("error", message=reason)
            return finish("rejected", reason)

    try:
        sandbox = await sandbox_factory()
        events.emit("run_started", run_id=run_id, task=task, sandbox_id=sandbox.sandbox_id,
                    model=provider.model, router=getattr(provider, "router", None) or "",
                    provider=provider.name, max_turns=max_turns, max_cost_usd=max_cost_usd)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        while True:
            if turns >= max_turns:
                return finish("max_turns", f"Stopped after {max_turns} turns without completing.")
            if time.monotonic() - started > timeout_s:
                return finish("timeout", f"Stopped after {timeout_s:.0f}s wall-clock timeout.")
            turns += 1
            completion = await provider.complete(messages, TOOL_SCHEMAS)
            usage.add(completion.usage)
            if is_real and budget is not None:
                budget.add(completion.usage.cost)
            if completion.model and completion.model != routed_model:
                routed_model = completion.model
                events.emit("model_routed", turn=turns, model=routed_model)
            events.emit("usage", turn=turns, **completion.usage.to_dict(),
                        cumulative=usage.to_dict())
            if completion.text:
                events.emit("assistant_text", turn=turns, text=completion.text)
            messages.append(completion.to_message())
            if not completion.tool_calls:
                return finish("complete", completion.text or "Done.")
            if usage.cost > max_cost_usd:
                return finish("max_cost", f"Stopped: run cost ${usage.cost:.4f} exceeded cap ${max_cost_usd:.2f}.")
            if is_real and budget is not None and budget.remaining() <= 0:
                return finish("budget_exhausted", "Stopped: global budget exhausted.")
            for call in completion.tool_calls:
                events.emit("tool_call", turn=turns, id=call.id, name=call.name, arguments=call.arguments)
                result = await run_tool(sandbox, call.name, call.arguments)
                if call.name == "bash" and "pytest" in call.arguments.get("command", ""):
                    tests = parse_pytest(result.get("stdout", "")) or tests
                if call.name == "edit_file" and result.get("diff"):
                    diffs.append(result["diff"])
                events.emit("tool_result", turn=turns, id=call.id, name=call.name, result=result)
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(result)})
    except asyncio.CancelledError:
        events.emit("error", message="run cancelled")
        return finish("cancelled", "Run cancelled.")
    except Exception as exc:  # noqa: BLE001 - surface as an error event, never crash the API
        events.emit("error", message=f"{type(exc).__name__}: {exc}")
        return finish("error", f"{type(exc).__name__}: {exc}")
    finally:
        if sandbox is not None:
            await sandbox.kill()
