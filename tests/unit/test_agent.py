"""Phase 3: providers, agent loop, events, cost and budget."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from agent.budget import Budget
from agent.cost import Usage, price_from_tokens, usage_from_response
from agent.events import EventLog
from agent.loop import SYSTEM_PROMPT, parse_pytest, run_agent
from agent.providers import Completion, OpenRouterProvider, ScriptedProvider, ToolCall, make_provider
from agent.sandbox import LocalSandbox

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "seed_repo"
MODEL = "anthropic/claude-haiku-4.5"


def seed_factory():
    return LocalSandbox.create(seed_dir=str(SEED))


class ListProvider:
    """Hand-built completions for loop edge cases."""

    name = "mock"
    model = "test/list"

    def __init__(self, completions, cost_per_turn: float = 0.0):
        self._items = list(completions)
        self._cost = cost_per_turn

    async def complete(self, messages, tools):
        c = self._items.pop(0) if self._items else Completion(text="done")
        c.usage = Usage(10, 5, 2, 15, self._cost)
        return c


# --- providers ---------------------------------------------------------------

async def test_scripted_provider_replays_fixture():
    p = ScriptedProvider.from_fixture("scripted_fix_run.json")
    first = await p.complete([], [])
    assert first.text and first.tool_calls[0].name == "bash"
    assert first.usage.cost == 0.0
    for _ in range(5):
        await p.complete([], [])
    final = await p.complete([], [])
    assert not final.tool_calls and "8 tests pass" in final.text
    assert "exhausted" in (await p.complete([], [])).text


def test_provider_selection_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(make_provider(), ScriptedProvider)
    assert isinstance(make_provider("mock"), ScriptedProvider)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        make_provider("openrouter")
    with pytest.raises(ValueError):
        make_provider("bogus")


def test_openrouter_provider_builds_without_network(monkeypatch):
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    p = OpenRouterProvider("sk-test")
    assert p.model == MODEL
    assert str(p._client.base_url).startswith("https://openrouter.ai/api/v1")
    cached = p._with_cache([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}])
    assert cached[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert cached[1] == {"role": "user", "content": "u"}


def test_completion_to_message():
    c = Completion(text="hi", tool_calls=[ToolCall("c1", "bash", {"command": "ls"})])
    m = c.to_message()
    assert m["tool_calls"][0]["function"]["arguments"] == '{"command": "ls"}'


# --- cost ---------------------------------------------------------------------

def test_cost_prefers_accounted_cost():
    u = usage_from_response(MODEL, {"prompt_tokens": 100, "completion_tokens": 50,
                                    "total_tokens": 150, "cost": 0.0123,
                                    "prompt_tokens_details": {"cached_tokens": 40}})
    assert (u.prompt_tokens, u.completion_tokens, u.cached_tokens, u.total_tokens) == (100, 50, 40, 150)
    assert u.cost == 0.0123


def test_cost_falls_back_to_config_prices():
    u = usage_from_response(MODEL, {"prompt_tokens": 1000, "completion_tokens": 200,
                                    "prompt_tokens_details": {"cached_tokens": 500}})
    expected = 500 * 1e-6 + 500 * 1e-7 + 200 * 5e-6
    assert u.cost == pytest.approx(expected)
    assert price_from_tokens("unknown/model", 1, 1) is None
    with pytest.raises(ValueError):
        usage_from_response("unknown/model", {"prompt_tokens": 1, "completion_tokens": 1})
    assert usage_from_response(MODEL, None).cost == 0.0


# --- budget -------------------------------------------------------------------

def test_budget_persists_and_caps(tmp_path):
    b = Budget(str(tmp_path / "spend.json"))
    assert b.snapshot() == {"spent": 0.0, "remaining": 4.0}
    b.add(0.018)
    assert Budget(str(tmp_path / "spend.json")).spent() == pytest.approx(0.018)
    assert b.can_start(0.25) == (True, "")
    b.add(3.9)
    assert b.can_start(0.25)[0] is False
    b.add(1.0)
    assert b.remaining() == 0.0
    assert b.can_start(0.01)[0] is False


async def test_budget_concurrent_adds(tmp_path):
    b = Budget(str(tmp_path / "spend.json"))
    await asyncio.gather(*[asyncio.to_thread(b.add, 0.01) for _ in range(50)])
    assert b.spent() == pytest.approx(0.5)


# --- events -------------------------------------------------------------------

async def test_event_log_replays_then_streams():
    log = EventLog()
    log.emit("run_started", a=1)
    received = []

    async def consume():
        async for e in log.stream():
            received.append(e.type)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    log.emit("assistant_text", text="x")
    log.emit("run_finished", status="complete")
    await task
    assert received == ["run_started", "assistant_text", "run_finished"]
    assert [e.seq for e in log.events] == [0, 1, 2]
    # Late subscriber gets full replay and closes.
    assert [e.type async for e in log.stream()] == received


# --- loop ---------------------------------------------------------------------

async def test_scripted_fix_reaches_eight_of_eight_on_local_sandbox():
    log = EventLog()
    result = await run_agent("Fix the parser so all tests pass", ScriptedProvider.from_fixture(),
                             seed_factory, log, max_turns=15)
    assert result.status == "complete"
    assert (result.tests_passed, result.tests_failed) == (8, 0)
    assert result.turns == 7
    assert result.usage.cost == 0.0
    assert result.sandbox_id.startswith("local_")
    assert "+SYMBOLS" in result.diff and "amount *= 1000" in result.diff
    types = [e.type for e in log.events]
    assert types[0] == "run_started" and types[-1] == "run_finished"
    assert types.count("tool_call") == 6 == types.count("tool_result")
    names = [e.data["name"] for e in log.events if e.type == "tool_call"]
    assert names == ["bash", "search", "read_file", "edit_file", "edit_file", "bash"]
    edit_results = [e for e in log.events if e.type == "tool_result" and e.data["name"] == "edit_file"]
    assert all(r.data["result"]["diff"].startswith("--- a/") for r in edit_results)
    finished = log.events[-1].data
    assert {"status", "summary", "tests_passed", "tests_failed", "turns", "tokens", "cost"} <= finished.keys()


async def test_event_ordering_within_turn():
    log = EventLog()
    await run_agent("t", ScriptedProvider.from_fixture(), seed_factory, log)
    seqs = [e.seq for e in log.events]
    assert seqs == list(range(len(seqs)))
    for i, e in enumerate(log.events):
        if e.type == "tool_call":
            assert log.events[i + 1].type == "tool_result"
            assert log.events[i + 1].data["id"] == e.data["id"]
    # Each turn: usage first, then text, then tool calls.
    turn1 = [e.type for e in log.events if e.data.get("turn") == 1]
    assert turn1 == ["usage", "assistant_text", "tool_call", "tool_result"]


async def test_system_prompt_and_messages_passed_to_provider():
    seen = {}

    class Spy(ListProvider):
        async def complete(self, messages, tools):
            seen["messages"] = messages
            seen["tools"] = tools
            return await super().complete(messages, tools)

    await run_agent("do it", Spy([]), seed_factory, EventLog())
    assert seen["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert seen["messages"][1] == {"role": "user", "content": "do it"}
    assert [t["function"]["name"] for t in seen["tools"]] == ["bash", "read_file", "write_file", "edit_file", "search"]


async def test_max_turns_enforced():
    looping = [Completion(text="", tool_calls=[ToolCall(f"c{i}", "bash", {"command": "true"})]) for i in range(10)]
    r = await run_agent("t", ListProvider(looping), seed_factory, EventLog(), max_turns=3)
    assert r.status == "max_turns" and r.turns == 3


async def test_max_cost_enforced():
    looping = [Completion(text="", tool_calls=[ToolCall(f"c{i}", "bash", {"command": "true"})]) for i in range(10)]
    r = await run_agent("t", ListProvider(looping, cost_per_turn=0.1), seed_factory, EventLog(), max_cost_usd=0.25)
    assert r.status == "max_cost" and r.turns == 3
    assert r.usage.cost == pytest.approx(0.3)


async def test_global_budget_guard_rejects_real_run(tmp_path):
    budget = Budget(str(tmp_path / "spend.json"))
    budget.add(3.9)
    real = ListProvider([], cost_per_turn=0.01)
    real.name = "openrouter"
    log = EventLog()
    r = await run_agent("t", real, seed_factory, log, budget=budget, max_cost_usd=0.25)
    assert r.status == "rejected" and r.sandbox_id is None
    assert log.events[0].type == "error"


async def test_real_run_tracks_spend_per_turn(tmp_path):
    budget = Budget(str(tmp_path / "spend.json"))
    real = ListProvider([Completion(text="", tool_calls=[ToolCall("c", "bash", {"command": "true"})])], cost_per_turn=0.01)
    real.name = "openrouter"
    r = await run_agent("t", real, seed_factory, EventLog(), budget=budget)
    assert r.turns == 2 and budget.spent() == pytest.approx(0.02)


async def test_mock_run_never_touches_budget(tmp_path):
    budget = Budget(str(tmp_path / "spend.json"))
    budget.add(4.0)
    r = await run_agent("t", ScriptedProvider.from_fixture(), seed_factory, EventLog(), budget=budget)
    assert r.status == "complete" and budget.spent() == 4.0


async def test_tool_errors_do_not_crash_loop():
    bad = [Completion(text="", tool_calls=[
        ToolCall("a", "read_file", {"path": "../../etc/passwd"}),
        ToolCall("b", "nope", {}),
        ToolCall("c", "edit_file", {"path": "missing.py", "old_str": "x", "new_str": "y"}),
    ])]
    log = EventLog()
    r = await run_agent("t", ListProvider(bad), seed_factory, log)
    assert r.status == "complete"
    errors = [e.data["result"]["error"] for e in log.events if e.type == "tool_result"]
    assert len(errors) == 3 and all(errors)


async def test_wall_clock_timeout():
    class Slow(ListProvider):
        async def complete(self, messages, tools):
            await asyncio.sleep(0.05)
            return Completion(text="", tool_calls=[ToolCall("c", "bash", {"command": "true"})])

    r = await run_agent("t", Slow([]), seed_factory, EventLog(), timeout_s=0.08, max_turns=50)
    assert r.status == "timeout"


async def test_sandbox_killed_on_provider_exception():
    created = []

    async def factory():
        sb = await LocalSandbox.create(seed_dir=str(SEED))
        created.append(sb)
        return sb

    class Boom(ListProvider):
        async def complete(self, messages, tools):
            raise RuntimeError("provider down")

    log = EventLog()
    r = await run_agent("t", Boom([]), factory, log)
    assert r.status == "error" and "provider down" in r.summary
    assert created[0].alive is False
    assert log.events[-2].type == "error" and log.events[-1].type == "run_finished"


async def test_usage_tracking_accumulates():
    log = EventLog()
    comps = [Completion(text="", tool_calls=[ToolCall("c", "bash", {"command": "true"})])]
    r = await run_agent("t", ListProvider(comps, cost_per_turn=0.001), seed_factory, log)
    assert r.usage.to_dict() == {"prompt_tokens": 20, "completion_tokens": 10, "cached_tokens": 4,
                                 "total_tokens": 30, "cost": 0.002}
    usage_events = [e for e in log.events if e.type == "usage"]
    assert [e.data["turn"] for e in usage_events] == [1, 2]
    assert usage_events[1].data["cumulative"]["total_tokens"] == 30


def test_parse_pytest():
    assert parse_pytest("2 failed, 6 passed in 0.1s") == (6, 2)
    assert parse_pytest("8 passed in 0.1s") == (8, 0)
    assert parse_pytest("no tests ran") is None


async def test_isolation_fixture_on_local_sandboxes():
    a = EventLog()
    b = EventLog()
    ra = await run_agent("write marker", ScriptedProvider.from_fixture("scripted_isolation_run.json", "run_a"), seed_factory, a)
    rb = await run_agent("check marker", ScriptedProvider.from_fixture("scripted_isolation_run.json", "run_b"), seed_factory, b)
    assert ra.sandbox_id != rb.sandbox_id
    read = [e for e in b.events if e.type == "tool_result" and e.data["name"] == "read_file"][0]
    assert "file not found" in read.data["result"]["error"]
    ls = [e for e in b.events if e.type == "tool_result" and e.data["name"] == "bash"][0]
    assert "ISOLATION_MARKER" not in ls.data["result"]["stdout"]
