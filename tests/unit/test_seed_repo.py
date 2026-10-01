"""Phase 1: the seed repo fails exactly two tests and the scripted fix repairs it."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "seed_repo"
FIXTURES = ROOT / "tests" / "fixtures"


def _run_pytest(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=cwd, capture_output=True, text=True,
    )


def _apply_fix_edits(workspace: Path) -> None:
    fixture = json.loads((FIXTURES / "scripted_fix_run.json").read_text())
    for turn in fixture["turns"]:
        for call in turn.get("tool_calls", []):
            if call["name"] != "edit_file":
                continue
            args = call["arguments"]
            target = workspace / args["path"]
            text = target.read_text()
            assert text.count(args["old_str"]) == 1
            target.write_text(text.replace(args["old_str"], args["new_str"]))


def test_seed_repo_has_exactly_two_failures(tmp_path: Path):
    ws = tmp_path / "ws"
    shutil.copytree(SEED, ws)
    result = _run_pytest(ws)
    assert result.returncode != 0
    assert "2 failed, 6 passed" in result.stdout
    assert "test_hk_dollar_prefix" in result.stdout
    assert "test_k_suffix" in result.stdout


def test_bug_shapes_match_spec():
    sys.path.insert(0, str(SEED))
    try:
        from listing_parser import parse_listing
    finally:
        sys.path.pop(0)
    assert parse_listing("Rolex 126710BLRO HK$98,000")["currency"] == "USD"
    assert parse_listing("Tudor 79830RB HKD 85k")["price"] == 85.0


def test_scripted_fix_reaches_eight_of_eight(tmp_path: Path):
    ws = tmp_path / "ws"
    shutil.copytree(SEED, ws)
    _apply_fix_edits(ws)
    result = _run_pytest(ws)
    assert result.returncode == 0, result.stdout
    assert "8 passed" in result.stdout


def test_fix_fixture_structure():
    fixture = json.loads((FIXTURES / "scripted_fix_run.json").read_text())
    names = [c["name"] for t in fixture["turns"] for c in t.get("tool_calls", [])]
    assert names == ["bash", "search", "read_file", "edit_file", "edit_file", "bash"]
    assert "pytest" in fixture["turns"][0]["tool_calls"][0]["arguments"]["command"]
    final = fixture["turns"][-1]
    assert "tool_calls" not in final and final["text"]
    for t in fixture["turns"]:
        assert isinstance(t["text"], str)
        for c in t.get("tool_calls", []):
            assert {"id", "name", "arguments"} <= c.keys()


def test_isolation_fixture_structure():
    fixture = json.loads((FIXTURES / "scripted_isolation_run.json").read_text())
    marker = fixture["marker"]
    a_calls = [c for t in fixture["run_a"]["turns"] for c in t.get("tool_calls", [])]
    b_calls = [c for t in fixture["run_b"]["turns"] for c in t.get("tool_calls", [])]
    assert [c["name"] for c in a_calls] == ["write_file"]
    assert a_calls[0]["arguments"]["path"] == marker
    assert [c["name"] for c in b_calls] == ["bash", "read_file"]
    assert b_calls[1]["arguments"]["path"] == marker
    assert "tool_calls" not in fixture["run_b"]["turns"][-1]
