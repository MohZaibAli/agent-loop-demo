"""Phase 2: tools and LocalSandbox."""

import os
from pathlib import Path

import pytest

from agent.sandbox import LocalSandbox, PathEscapeError, resolve_in_workspace
from agent.tools import run_tool, truncate

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "seed_repo"


@pytest.fixture
async def sb():
    sandbox = await LocalSandbox.create(seed_dir=str(SEED))
    yield sandbox
    await sandbox.kill()


def test_resolve_confines_to_workspace(tmp_path: Path):
    assert resolve_in_workspace(str(tmp_path), "a/b.py") == str(tmp_path / "a" / "b.py")
    assert resolve_in_workspace(str(tmp_path), ".") == str(tmp_path)


@pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd", "a/../../x", "../"])
def test_resolve_rejects_traversal(tmp_path: Path, bad: str):
    with pytest.raises(PathEscapeError):
        resolve_in_workspace(str(tmp_path), bad)


def test_resolve_rejects_symlink_escape(tmp_path: Path):
    (tmp_path / "link").symlink_to("/etc")
    with pytest.raises(PathEscapeError):
        resolve_in_workspace(str(tmp_path), "link/passwd")


def test_truncate_keeps_head_and_tail():
    text = "H" * 6000 + "T" * 6000
    out = truncate(text)
    assert out.startswith("H" * 100) and out.endswith("T" * 100)
    assert "[truncated 2000 chars]" in out
    assert truncate("short") == "short"


async def test_bash_returns_exit_code_and_streams(sb: LocalSandbox):
    res = await run_tool(sb, "bash", {"command": "echo out; echo err >&2; exit 3"})
    assert res == {"exit_code": 3, "stdout": "out\n", "stderr": "err\n"}


async def test_bash_timeout(sb: LocalSandbox):
    res = await run_tool(sb, "bash", {"command": "sleep 5", "timeout_s": 0.2})
    assert res["exit_code"] == 124 and "timed out" in res["stderr"]


async def test_bash_output_truncated(sb: LocalSandbox):
    res = await run_tool(sb, "bash", {"command": "python -c \"print('x'*20000)\""})
    assert "[truncated" in res["stdout"] and len(res["stdout"]) < 11_000


async def test_read_file_line_numbers(sb: LocalSandbox):
    res = await run_tool(sb, "read_file", {"path": "listing_parser/parser.py", "offset": 2, "limit": 1})
    assert res["content"].startswith("    3  ")
    assert res["total_lines"] > 50


async def test_read_file_rejects_traversal(sb: LocalSandbox):
    res = await run_tool(sb, "read_file", {"path": "../../etc/passwd"})
    assert "escapes workspace" in res["error"]


async def test_read_missing_file_is_structured_error(sb: LocalSandbox):
    res = await run_tool(sb, "read_file", {"path": "nope.py"})
    assert "file not found" in res["error"]


async def test_write_file_creates_and_confines(sb: LocalSandbox):
    res = await run_tool(sb, "write_file", {"path": "new/dir/x.txt", "content": "hi"})
    assert res["bytes"] == 2
    assert await sb.read_text("new/dir/x.txt") == "hi"
    res = await run_tool(sb, "write_file", {"path": "/tmp/escape.txt", "content": "x"})
    assert "escapes workspace" in res["error"]


async def test_edit_zero_match(sb: LocalSandbox):
    res = await run_tool(sb, "edit_file", {"path": "listing_parser/parser.py", "old_str": "nope", "new_str": "x"})
    assert res["error"] == "old_str not found in file"


async def test_edit_multiple_match(sb: LocalSandbox):
    res = await run_tool(sb, "edit_file", {"path": "listing_parser/parser.py", "old_str": "return", "new_str": "x"})
    assert "matched" in res["error"]


async def test_edit_single_match_returns_diff(sb: LocalSandbox):
    res = await run_tool(sb, "edit_file", {
        "path": "listing_parser/parser.py",
        "old_str": "    \"tudor\": \"Tudor\",\n", "new_str": "    \"tudor\": \"Tudor\",\n    \"breitling\": \"Breitling\",\n"})
    assert res["diff"].startswith("--- a/listing_parser/parser.py\n+++ b/listing_parser/parser.py\n")
    assert '+    "breitling": "Breitling",' in res["diff"]
    assert "breitling" in await sb.read_text("listing_parser/parser.py")


async def test_search_finds_matches(sb: LocalSandbox):
    res = await run_tool(sb, "search", {"pattern": "CURRENCY_RE", "path": "listing_parser"})
    assert res["count"] >= 2
    assert "listing_parser/parser.py" in res["matches"]


async def test_search_with_glob_and_no_match(sb: LocalSandbox):
    res = await run_tool(sb, "search", {"pattern": "CURRENCY_RE", "glob": "*.md"})
    assert res == {"matches": "", "count": 0}


async def test_search_falls_back_to_grep(sb: LocalSandbox, monkeypatch):
    # Hide every rg on PATH; the tool must still work via grep -rn.
    bindir = Path(sb.workspace) / ".nobin"
    bindir.mkdir()
    for exe in ("grep", "sh", "bash", "python"):
        src = os.popen(f"command -v {exe}").read().strip()
        if src:
            (bindir / exe).symlink_to(src)
    monkeypatch.setenv("PATH", str(bindir))
    res = await run_tool(sb, "search", {"pattern": "def parse_listing", "path": "listing_parser"})
    assert res["count"] == 1


async def test_unknown_tool_and_bad_args(sb: LocalSandbox):
    assert "unknown tool" in (await run_tool(sb, "rm_rf", {}))["error"]
    assert "invalid arguments" in (await run_tool(sb, "bash", {}))["error"]


async def test_local_sandbox_lifecycle():
    sb = await LocalSandbox.create(seed_dir=str(SEED))
    assert sb.sandbox_id.startswith("local_")
    assert await sb.exists("listing_parser/parser.py")
    res = await sb.run("python -m pytest -q")
    assert "2 failed, 6 passed" in res.stdout
    await sb.kill()
    assert not Path(sb.workspace).exists()
