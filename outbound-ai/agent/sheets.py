"""Google Sheets reader/writer and its in-memory fixture twin.

The sheet is the system of record for leads. Both backends expose the same
small interface so the workflow never knows which one it is talking to:

    read_leads()                -> list[Lead]
    mark_called(row, when)      -> None   (Call Made = true, Date & Time = ts)

`FixtureSheet` loads `fixtures/leads.json` into memory and is the default for
development, tests, CI and the demo UI. `GoogleSheet` wraps gspread with a
service account. Row numbers are 1-based sheet rows (header is row 1).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

COLUMNS = [
    "User Phone Number",
    "First Name",
    "Job Title",
    "Current Job Description",
    "New Job Opportunity",
    "Date & Time",
    "Call Made",
]
PHONE, FIRST_NAME, JOB_TITLE, CURRENT_JOB, NEW_JOB, DATE_TIME, CALL_MADE = COLUMNS

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "fixtures" / "leads.json"

TRUE_VALUES = {"true", "yes", "1", "y", "x", "done"}


def is_called(value: object) -> bool:
    """`Call Made` is treated as true only for an explicit truthy marker."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in TRUE_VALUES


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Lead:
    row: int  # 1-based sheet row (header is row 1, first lead is row 2)
    phone: str
    first_name: str
    job_title: str
    current_job_description: str
    new_job_opportunity: str
    date_time: str = ""
    call_made: bool = False

    @classmethod
    def from_record(cls, row: int, record: dict) -> "Lead":
        g = lambda k: str(record.get(k, "") or "").strip()  # noqa: E731
        return cls(
            row=row,
            phone=g(PHONE),
            first_name=g(FIRST_NAME),
            job_title=g(JOB_TITLE),
            current_job_description=g(CURRENT_JOB),
            new_job_opportunity=g(NEW_JOB),
            date_time=g(DATE_TIME),
            call_made=is_called(record.get(CALL_MADE)),
        )

    def to_record(self) -> dict:
        return {
            PHONE: self.phone,
            FIRST_NAME: self.first_name,
            JOB_TITLE: self.job_title,
            CURRENT_JOB: self.current_job_description,
            NEW_JOB: self.new_job_opportunity,
            DATE_TIME: self.date_time,
            CALL_MADE: "true" if self.call_made else "",
        }

    def dynamic_variables(self) -> dict[str, str]:
        """The `retell_llm_dynamic_variables` payload for this lead."""
        return {
            "first_name": self.first_name,
            "job_title": self.job_title,
            "current_job_description": self.current_job_description,
            "new_job_opportunity": self.new_job_opportunity,
        }

    def to_dict(self) -> dict:
        return {
            "row": self.row,
            "phone": self.phone,
            "first_name": self.first_name,
            "job_title": self.job_title,
            "current_job_description": self.current_job_description,
            "new_job_opportunity": self.new_job_opportunity,
            "date_time": self.date_time,
            "call_made": self.call_made,
        }


def filter_pending(leads: list[Lead]) -> list[Lead]:
    """Step 2 of the workflow: keep rows where `Call Made` is empty or false."""
    return [lead for lead in leads if not lead.call_made]


class Sheet(Protocol):
    name: str

    def read_leads(self) -> list[Lead]: ...
    def mark_called(self, row: int, when: str | None = None) -> Lead: ...


class SchemaError(ValueError):
    pass


def validate_header(header: list[str]) -> None:
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise SchemaError(f"sheet is missing columns: {missing}")


@dataclass
class FixtureSheet:
    """In-memory sheet seeded from a JSON fixture. Writes stay in memory."""

    records: list[dict] = field(default_factory=list)
    name: str = "fixture"

    @classmethod
    def load(cls, path: str | Path | None = None) -> "FixtureSheet":
        data = json.loads(Path(path or FIXTURE_PATH).read_text())
        validate_header(data["columns"])
        return cls(records=[dict(r) for r in data["rows"]])

    def read_leads(self) -> list[Lead]:
        return [Lead.from_record(i + 2, r) for i, r in enumerate(self.records)]

    def mark_called(self, row: int, when: str | None = None) -> Lead:
        idx = row - 2
        if idx < 0 or idx >= len(self.records):
            raise IndexError(f"row {row} out of range")
        self.records[idx][CALL_MADE] = "true"
        self.records[idx][DATE_TIME] = when or now_iso()
        return Lead.from_record(row, self.records[idx])

    def reset(self, path: str | Path | None = None) -> None:
        self.records = FixtureSheet.load(path).records


class GoogleSheet:
    """gspread-backed sheet. Credentials: GOOGLE_SERVICE_ACCOUNT_JSON (JSON string or file path)."""

    name = "google"

    def __init__(self, sheet_id: str, worksheet: str = "Sheet1", credentials: str | None = None):
        import gspread  # imported lazily so the fixture path needs no network libs

        creds = credentials or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not creds:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required for SHEETS_PROVIDER=google")
        if creds.lstrip().startswith("{"):
            client = gspread.service_account_from_dict(json.loads(creds))
        else:
            client = gspread.service_account(filename=creds)
        self.ws = client.open_by_key(sheet_id).worksheet(worksheet)
        self.header: list[str] = self.ws.row_values(1)
        validate_header(self.header)

    def read_leads(self) -> list[Lead]:
        records = self.ws.get_all_records(expected_headers=COLUMNS)
        return [Lead.from_record(i + 2, r) for i, r in enumerate(records)]

    def mark_called(self, row: int, when: str | None = None) -> Lead:
        when = when or now_iso()
        self.ws.update_cell(row, self.header.index(CALL_MADE) + 1, "true")
        self.ws.update_cell(row, self.header.index(DATE_TIME) + 1, when)
        values = self.ws.row_values(row)
        record = dict(zip(self.header, values + [""] * (len(self.header) - len(values))))
        return Lead.from_record(row, record)


def make_sheet() -> Sheet:
    """Factory driven by SHEETS_PROVIDER. Anything but `google` is the fixture."""
    if os.environ.get("SHEETS_PROVIDER", "fixture").lower() == "google":
        return GoogleSheet(
            sheet_id=os.environ["GOOGLE_SHEET_ID"],
            worksheet=os.environ.get("GOOGLE_WORKSHEET_NAME", "Sheet1"),
        )
    return FixtureSheet.load()
