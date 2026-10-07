import json
from datetime import datetime

import pytest

from agent.sheets import (
    CALL_MADE, COLUMNS, DATE_TIME, FixtureSheet, Lead, SchemaError, filter_pending, is_called, now_iso,
)
from agent.fixtures import load_scripted_run, render


def test_fixture_matches_sheet_schema(sheet):
    assert all(set(COLUMNS) <= set(r) for r in sheet.records)
    assert len(sheet.records) == 5


def test_read_leads_rows_are_1_based_after_header(sheet):
    leads = sheet.read_leads()
    assert [l.row for l in leads] == [2, 3, 4, 5, 6]
    assert leads[0].first_name == "Amelia"
    assert leads[0].phone.startswith("+1")


@pytest.mark.parametrize("value,expected", [
    ("", False), (None, False), ("false", False), ("FALSE", False), ("0", False), ("no", False),
    ("true", True), ("TRUE", True), ("True", True), ("yes", True), ("1", True), (True, True), (False, False),
])
def test_is_called(value, expected):
    assert is_called(value) is expected


def test_filter_pending_keeps_empty_and_false(sheet):
    pending = filter_pending(sheet.read_leads())
    assert [l.first_name for l in pending] == ["Amelia", "Marcus", "Daniel"]
    assert all(not l.call_made for l in pending)


def test_mark_called_updates_status_and_timestamp(sheet):
    updated = sheet.mark_called(2, when="2026-10-07T10:00:00Z")
    assert updated.call_made is True
    assert updated.date_time == "2026-10-07T10:00:00Z"
    assert sheet.records[0][CALL_MADE] == "true"
    assert sheet.records[0][DATE_TIME] == "2026-10-07T10:00:00Z"
    assert [l.first_name for l in filter_pending(sheet.read_leads())] == ["Marcus", "Daniel"]


def test_mark_called_defaults_to_utc_now(sheet):
    updated = sheet.mark_called(3)
    assert updated.date_time.endswith("Z")
    datetime.fromisoformat(updated.date_time.replace("Z", "+00:00"))


def test_mark_called_out_of_range(sheet):
    with pytest.raises(IndexError):
        sheet.mark_called(1)
    with pytest.raises(IndexError):
        sheet.mark_called(99)


def test_reset_restores_fixture(sheet):
    sheet.mark_called(2)
    sheet.reset()
    assert len(filter_pending(sheet.read_leads())) == 3


def test_dynamic_variables_payload(sheet):
    lead = sheet.read_leads()[0]
    assert set(lead.dynamic_variables()) == {
        "first_name", "job_title", "current_job_description", "new_job_opportunity",
    }
    assert lead.dynamic_variables()["job_title"] == "Registered Nurse"


def test_lead_round_trip():
    lead = Lead(row=2, phone="+1", first_name="A", job_title="B", current_job_description="C",
                new_job_opportunity="D", call_made=True, date_time="t")
    assert Lead.from_record(2, lead.to_record()) == lead


def test_schema_validation(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"columns": ["First Name"], "rows": []}))
    with pytest.raises(SchemaError):
        FixtureSheet.load(bad)


def test_now_iso_format():
    assert now_iso().endswith("Z") and "T" in now_iso()


def test_scripted_run_fixture_and_render():
    data = load_scripted_run()
    assert data["sms"]["status"] == "queued"
    assert render(data["call"]["transcript_preview"], {"first_name": "Amelia", "new_job_opportunity": "X"}).startswith("Hi Amelia")
    assert render("Hi {{first_name}}", {"first_name": "Bo"}) == "Hi Bo"


def test_add_lead_appends_pending_row(sheet):
    lead = sheet.add_lead({"User Phone Number": "+15550100042", "First Name": "Zed"})
    assert lead.row == 7 and lead.call_made is False and lead.job_title == ""
    assert len(filter_pending(sheet.read_leads())) == 4
