"""Loader for the scripted mock-run fixture used by the mock providers."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTED_RUN = ROOT / "fixtures" / "scripted_call_run.json"


@lru_cache(maxsize=1)
def load_scripted_run(path: str | Path | None = None) -> dict:
    data = json.loads(Path(path or SCRIPTED_RUN).read_text())
    for key in ("sms", "call"):
        if key not in data:
            raise ValueError(f"scripted run fixture is missing '{key}'")
    return data


def render(template: str, variables: dict[str, str]) -> str:
    """Tiny `{{var}}` renderer shared by the SMS template and mock transcripts."""
    out = template
    for k, v in variables.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out
