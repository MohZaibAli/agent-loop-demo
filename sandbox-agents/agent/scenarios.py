"""Seed repositories the agent can be pointed at."""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

SCENARIOS: dict[str, dict[str, Any]] = {
    "listing_parser": {
        "dir": ROOT / "seed_repo",
        "title": "Watch-dealer listing parser",
        "task": "Fix the parser so all tests pass",
        "shape": "1 module · 8 tests · 2 failing",
        "mock": True,  # the prototype: the scripted fixture replays this one
    },
    "invoice_engine": {
        "dir": ROOT / "scenarios" / "invoice_engine",
        "title": "Invoice totals and credits",
        "task": "Several invoice tests fail and credits are not implemented. Fix the rounding and tax bugs, "
                "implement apply_credit as described in its docstring, and make the whole suite pass.",
        "shape": "2 modules · 10 tests · 8 failing · 1 function to implement",
        "mock": False,
    },
    "log_pipeline": {
        "dir": ROOT / "scenarios" / "log_pipeline",
        "title": "Access-log metrics pipeline",
        "task": "The log pipeline tests fail. Diagnose and fix every bug in the parser and metrics modules "
                "without changing the tests, then confirm the suite is green.",
        "shape": "2 modules · 9 tests · 6 failing",
        "mock": False,
    },
}
DEFAULT_SCENARIO = "listing_parser"


def list_scenarios() -> list[dict[str, Any]]:
    return [{"id": k, "title": v["title"], "task": v["task"], "shape": v["shape"], "mock": v["mock"]}
            for k, v in SCENARIOS.items()]


def scenario_dir(name: str) -> Path:
    return SCENARIOS[name]["dir"]
