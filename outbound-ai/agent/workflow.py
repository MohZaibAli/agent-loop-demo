"""Core orchestration: FETCH_SHEETS -> FILTER_LEADS -> SEND_SMS -> WAIT -> RETELL_CALL -> UPDATE_SHEET."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

from agent.budget import Budget
from agent.config import load_config
from agent.events import EventLog
from agent.providers import Providers
from agent.sheets import Lead, Sheet, filter_pending, now_iso


def wait_seconds(mock: bool) -> float:
    cfg = load_config()["defaults"]
    if mock:
        return float(os.environ.get("WAIT_SECONDS_MOCK", cfg["wait_seconds_mock"]))
    return float(os.environ.get("WAIT_SECONDS", cfg["wait_seconds"]))


@dataclass
class RunResult:
    status: str  # completed | failed | skipped
    leads_total: int = 0
    leads_pending: int = 0
    leads_processed: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    error: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "leads_total": self.leads_total, "leads_pending": self.leads_pending,
                "leads_processed": self.leads_processed, "cost_usd": round(self.cost_usd, 6),
                "duration_s": round(self.duration_s, 3), "error": self.error, "calls": self.calls}


async def run_workflow(sheet: Sheet, providers: Providers, events: EventLog, budget: Budget, *,
                       run_id: str, max_leads: int | None = None, lead_row: int | None = None,
                       wait_s: float | None = None, tick_s: float = 1.0) -> RunResult:
    """Process pending leads. `lead_row` restricts the run to one sheet row."""
    started = time.monotonic()
    result = RunResult(status="running")
    cfg = load_config()["defaults"]
    max_leads = max_leads or int(cfg["max_leads_per_run"])
    delay = wait_seconds(providers.mock) if wait_s is None else wait_s
    mode = "MOCK" if providers.mock else "LIVE"

    def finish(status: str, error: str | None = None) -> RunResult:
        result.status, result.error = status, error
        result.duration_s = time.monotonic() - started
        events.emit("run_finished", run_id=run_id, mode=mode, **result.to_dict())
        return result

    try:
        # 1. FETCH_SHEETS
        events.emit("step_start", "FETCH_SHEETS", run_id=run_id, mode=mode, sheet=sheet.name)
        leads = await asyncio.to_thread(sheet.read_leads)
        result.leads_total = len(leads)
        events.emit("step_payload", "FETCH_SHEETS", rows=[l.to_dict() for l in leads])
        events.emit("step_complete", "FETCH_SHEETS", rows_fetched=len(leads))

        # 2. FILTER_LEADS
        events.emit("step_start", "FILTER_LEADS", rule="Call Made is empty or false")
        pending = filter_pending(leads)
        skipped = [l for l in leads if l.call_made]
        if lead_row is not None:
            pending = [l for l in pending if l.row == lead_row]
        pending = pending[:max_leads]
        result.leads_pending = len(pending)
        events.emit("step_payload", "FILTER_LEADS",
                    pending=[{"row": l.row, "first_name": l.first_name, "phone": l.phone} for l in pending],
                    skipped=[{"row": l.row, "first_name": l.first_name, "reason": "Call Made = true"} for l in skipped])
        events.emit("step_complete", "FILTER_LEADS", pending=len(pending), skipped=len(skipped))
        if not pending:
            return finish("skipped", "no pending leads")

        estimate = budget.estimate_lead() * len(pending)
        ok, reason = budget.can_start(0.0 if providers.mock else estimate)
        if not ok:
            events.emit("step_error", "FILTER_LEADS", error=reason, estimate_usd=estimate)
            return finish("failed", reason)

        for lead in pending:
            await _process_lead(lead, sheet, providers, events, budget, result, delay, tick_s)
        return finish("completed")
    except Exception as exc:  # noqa: BLE001
        events.emit("step_error", None, error=f"{type(exc).__name__}: {exc}")
        return finish("failed", str(exc))


async def _process_lead(lead: Lead, sheet: Sheet, providers: Providers, events: EventLog, budget: Budget,
                        result: RunResult, delay: float, tick_s: float) -> None:
    variables = lead.dynamic_variables()
    ctx = {"row": lead.row, "lead": lead.first_name, "to": lead.phone}

    # 3. SEND_SMS
    events.emit("step_start", "SEND_SMS", **ctx, provider=providers.sms.name)
    sms = await providers.sms.send_sms(lead.phone, variables)
    cost = 0.0 if sms.mock else sms.price_usd
    events.emit("step_payload", "SEND_SMS", **ctx, sms=sms.to_dict())
    events.emit("step_complete", "SEND_SMS", **ctx, sid=sms.sid, status=sms.status, cost_usd=cost)
    if cost:
        budget.add(cost)
    result.cost_usd += cost

    # 4. WAIT
    events.emit("step_start", "WAIT", **ctx, seconds=delay)
    elapsed = 0.0
    while elapsed < delay:
        step = min(tick_s, delay - elapsed)
        await asyncio.sleep(step)
        elapsed += step
        events.emit("step_payload", "WAIT", **ctx, elapsed_s=round(elapsed, 2), total_s=delay)
    events.emit("step_complete", "WAIT", **ctx, waited_s=delay)

    # 5. RETELL_CALL
    events.emit("step_start", "RETELL_CALL", **ctx, provider=providers.calls.name)
    call = await providers.calls.create_call(lead.phone, variables)
    call_cost = 0.0 if call.mock else budget.call_cost()
    events.emit("step_payload", "RETELL_CALL", **ctx, request=call.request, response=call.response)
    events.emit("step_complete", "RETELL_CALL", **ctx, call_id=call.call_id, call_status=call.call_status,
                cost_usd=call_cost)
    if call_cost:
        budget.add(call_cost)
    result.cost_usd += call_cost

    # 6. UPDATE_SHEET
    ts = now_iso()
    events.emit("step_start", "UPDATE_SHEET", **ctx, sheet=sheet.name)
    updated = await asyncio.to_thread(sheet.mark_called, lead.row, ts)
    events.emit("step_payload", "UPDATE_SHEET", **ctx, write={"Call Made": "true", "Date & Time": ts})
    events.emit("step_complete", "UPDATE_SHEET", **ctx, call_made=updated.call_made, date_time=updated.date_time)

    result.leads_processed += 1
    result.calls.append({"row": lead.row, "first_name": lead.first_name, "to": lead.phone,
                         "sms_sid": sms.sid, "call_id": call.call_id, "cost_usd": cost + call_cost})
