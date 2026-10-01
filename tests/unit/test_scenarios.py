"""Scenarios are solvable, start broken by the documented amount, and uploads are safe."""

import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from agent.scenarios import SCENARIOS, BadUpload, extract_upload, list_scenarios

ROOT = Path(__file__).resolve().parents[2]
SOLUTIONS = ROOT / "tests" / "fixtures" / "solutions"
EXPECTED_FAILING = {"listing_parser": 2, "invoice_engine": 8, "log_pipeline": 6}


def _pytest(cwd: Path) -> str:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                          cwd=cwd, capture_output=True, text=True).stdout


@pytest.mark.parametrize("name", list(EXPECTED_FAILING))
def test_scenario_starts_with_expected_failures(name: str, tmp_path: Path):
    ws = tmp_path / name
    shutil.copytree(SCENARIOS[name]["dir"], ws, ignore=shutil.ignore_patterns("__pycache__"))
    assert f"{EXPECTED_FAILING[name]} failed" in _pytest(ws)


@pytest.mark.parametrize("name", ["invoice_engine", "log_pipeline"])
def test_scenario_reference_fix_is_green(name: str, tmp_path: Path):
    ws = tmp_path / "a"
    shutil.copytree(SCENARIOS[name]["dir"], ws, ignore=shutil.ignore_patterns("__pycache__"))
    patch = subprocess.run(["patch", "-p1", "-s", "-i", str(SOLUTIONS / f"{name}.patch")], cwd=ws,
                           capture_output=True, text=True)
    assert patch.returncode == 0, patch.stdout + patch.stderr
    out = _pytest(ws)
    assert "failed" not in out and "passed" in out


def test_list_scenarios_shape():
    items = list_scenarios()
    assert [i["id"] for i in items] == ["listing_parser", "invoice_engine", "log_pipeline"]
    assert items[0]["mock"] is True and all(not i["mock"] for i in items[1:])
    assert all(i["task"] and i["title"] and i["shape"] for i in items)


def _zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_extract_upload_flattens_single_top_folder():
    target = extract_upload(_zip({"repo-main/pkg/__init__.py": "", "repo-main/tests/test_x.py": "def test_a(): pass"}))
    try:
        assert (target / "pkg" / "__init__.py").exists()
        assert (target / "tests" / "test_x.py").exists()
        assert not (target / "repo-main").exists()
    finally:
        shutil.rmtree(target)


def test_extract_upload_rejects_escapes_and_junk():
    with pytest.raises(BadUpload, match="unsafe path"):
        extract_upload(_zip({"../evil.py": "x"}))
    with pytest.raises(BadUpload, match="not a valid zip"):
        extract_upload(b"definitely not a zip")
    with pytest.raises(BadUpload, match="no Python"):
        extract_upload(_zip({"README.md": "hi"}))
    with pytest.raises(BadUpload, match="larger"):
        extract_upload(b"0" * (26 * 1024 * 1024))
