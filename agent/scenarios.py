"""Seed repositories the agent can be pointed at, plus uploaded-zip workspaces."""

from __future__ import annotations

import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAX_ZIP_BYTES = 25 * 1024 * 1024
MAX_UNPACKED_BYTES = 100 * 1024 * 1024

SCENARIOS: dict[str, dict[str, Any]] = {
    "listing_parser": {
        "dir": ROOT / "seed_repo",
        "title": "Watch-dealer listing parser",
        "task": "Fix the parser so all tests pass",
        "shape": "1 module · 8 tests · 2 failing",
        "mock": True,  # the scripted fixture replays this one
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


class BadUpload(ValueError):
    pass


def extract_upload(data: bytes) -> Path:
    """Unpack an uploaded zip into a fresh temp dir, refusing path escapes and oversized archives.

    A single top-level folder (as in GitHub zips) is flattened away. Caller removes the dir.
    """
    if len(data) > MAX_ZIP_BYTES:
        raise BadUpload(f"zip larger than {MAX_ZIP_BYTES // 1024 // 1024} MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BadUpload("not a valid zip file") from exc
    target = Path(tempfile.mkdtemp(prefix="agent-upload-")).resolve()
    try:
        total = 0
        for info in archive.infolist():
            name = info.filename
            if name.startswith("__MACOSX/") or not name or name.endswith("/"):
                continue
            dest = (target / name).resolve()
            if target not in dest.parents:
                raise BadUpload(f"unsafe path in zip: {name}")
            total += info.file_size
            if total > MAX_UNPACKED_BYTES:
                raise BadUpload("zip unpacks to more than 100 MB")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        entries = [p for p in target.iterdir() if p.name != "__MACOSX"]
        if len(entries) == 1 and entries[0].is_dir():
            inner = entries[0]
            for child in inner.iterdir():
                shutil.move(str(child), target / child.name)
            inner.rmdir()
        if not any(target.rglob("*.py")):
            raise BadUpload("zip contains no Python files")
        return target
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
