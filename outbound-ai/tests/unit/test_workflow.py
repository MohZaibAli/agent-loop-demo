import pytest

from agent.budget import Budget
from agent.events import STEPS, EventLog
from agent.providers import Providers
from agent.retell import MockRetellClient
from agent.sheets import FixtureSheet, filter_pending
from agent.twilio_client import MockTwilioClient
from agent.workflow import run_workflow, wait_seconds


@pytest.fixture
def budget(tmp_path):
    return Budget(path=str(tmp_path / "spend.json"))


def mock_providers() -> Providers:
    return Providers(name="mock", sms=MockTwilioClient(), calls=MockRetellClient())


async def test_full_mock_pipeline_processes_pending_leads(budget):
    sheet = FixtureSheet.load()
    events = EventLog()
    res = await run_workflow(sheet, mock_providers(), events, budget, run_id="run_t", wait_s=0.02, tick_s=0.01)
    assert res.status == "completed"
    assert (res.leads_total, res.leads_pending, res.leads_processed) == (5, 3, 3)
    assert res.cost_usd == 0.0 and budget.spent() == 0.0
    assert filter_pending(sheet.read_leads()) == []
    assert events.done and events.events[-1].type == "run_finished"
    starts = [e.step for e in events.events if e.type == "step_start"]
    assert starts[:2] == ["FETCH_SHEETS", "FILTER_LEADS"]
    assert starts[2:6] == ["SEND_SMS", "WAIT", "RETELL_CALL", "UPDATE_SHEET"]
    assert set(starts) == set(STEPS)
    completes = [e for e in events.events if e.type == "step_complete" and e.step == "RETELL_CALL"]
    assert len(completes) == 3 and all(e.data["call_id"].startswith("call_mock_") for e in completes)


async def test_single_lead_run(budget):
    sheet = FixtureSheet.load()
    events = EventLog()
    res = await run_workflow(sheet, mock_providers(), events, budget, run_id="r", lead_row=3, wait_s=0, tick_s=0.01)
    assert res.leads_processed == 1 and res.calls[0]["first_name"] == "Marcus"
    assert sheet.read_leads()[1].call_made is True
    assert sheet.read_leads()[0].call_made is False


async def test_skipped_when_nothing_pending(budget):
    sheet = FixtureSheet.load()
    for row in (2, 3, 5):
        sheet.mark_called(row)
    res = await run_workflow(sheet, mock_providers(), EventLog(), budget, run_id="r", wait_s=0)
    assert res.status == "skipped" and res.leads_processed == 0


async def test_wait_emits_ticker(budget):
    events = EventLog()
    await run_workflow(FixtureSheet.load(), mock_providers(), events, budget, run_id="r", lead_row=2,
                       wait_s=0.03, tick_s=0.01)
    ticks = [e for e in events.events if e.step == "WAIT" and e.type == "step_payload"]
    assert len(ticks) >= 2 and ticks[-1].data["elapsed_s"] == pytest.approx(0.03, abs=0.01)


async def test_budget_guard_blocks_live_run_over_ceiling(tmp_path):
    budget = Budget(path=str(tmp_path / "s.json"), ceiling=0.01)
    live_shaped = Providers(name="live", sms=MockTwilioClient(), calls=MockRetellClient())
    events = EventLog()
    res = await run_workflow(FixtureSheet.load(), live_shaped, events, budget, run_id="r", wait_s=0)
    assert res.status == "failed" and "exceeds remaining" in res.error
    assert any(e.type == "step_error" for e in events.events)


def test_budget_persistence_and_costs(budget):
    assert budget.sms_cost() == 0.0079 and budget.call_cost() == pytest.approx(0.42)
    budget.add(1.5)
    assert Budget(path=str(budget.path)).spent() == 1.5
    assert budget.snapshot()["remaining"] == pytest.approx(budget.ceiling - 1.5)


def test_wait_seconds_defaults(monkeypatch):
    monkeypatch.delenv("WAIT_SECONDS", raising=False)
    monkeypatch.delenv("WAIT_SECONDS_MOCK", raising=False)
    assert wait_seconds(True) == 5 and wait_seconds(False) == 600


async def test_event_stream_replays_then_lives():
    log = EventLog()
    log.emit("step_start", "FETCH_SHEETS", a=1)
    seen = []

    async def consume():
        async for ev in log.stream():
            seen.append(ev.type)

    import asyncio
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    log.emit("run_finished")
    await task
    assert seen == ["step_start", "run_finished"]
    d = log.events[0].to_dict()
    assert set(d) == {"event_id", "seq", "timestamp", "type", "step", "data"}
