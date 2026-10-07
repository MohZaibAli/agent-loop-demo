"""Tools the agent can call. Every tool runs against a Sandbox and never raises."""

from __future__ import annotations

import difflib
import shlex
from typing import Any, Awaitable, Callable

from agent.sandbox import PathEscapeError, Sandbox, resolve_in_workspace

MAX_OUTPUT = 10_000
ToolFn = Callable[[Sandbox, dict[str, Any]], Awaitable[dict[str, Any]]]


def truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    """Keep head and tail of oversized output."""
    if len(text) <= limit:
        return text
    half = limit // 2
    dropped = len(text) - limit
    return f"{text[:half]}\n...[truncated {dropped} chars]...\n{text[-half:]}"


def _rel(sandbox: Sandbox, path: str) -> str:
    """Return the resolved path, raising PathEscapeError on escape."""
    return resolve_in_workspace(sandbox.workspace, path)


async def bash(sandbox: Sandbox, args: dict[str, Any]) -> dict[str, Any]:
    timeout = float(args.get("timeout_s", 60))
    result = await sandbox.run(args["command"], timeout_s=timeout)
    return {
        "exit_code": result.exit_code,
        "stdout": truncate(result.stdout),
        "stderr": truncate(result.stderr),
    }


async def read_file(sandbox: Sandbox, args: dict[str, Any]) -> dict[str, Any]:
    path = _rel(sandbox, args["path"])
    offset = int(args.get("offset", 0))
    limit = int(args.get("limit", 400))
    lines = (await sandbox.read_text(path)).splitlines()
    window = lines[offset : offset + limit]
    numbered = "\n".join(f"{offset + i + 1:>5}  {line}" for i, line in enumerate(window))
    return {"path": args["path"], "content": truncate(numbered), "total_lines": len(lines)}


async def write_file(sandbox: Sandbox, args: dict[str, Any]) -> dict[str, Any]:
    path = _rel(sandbox, args["path"])
    await sandbox.write_text(path, args["content"])
    return {"path": args["path"], "bytes": len(args["content"].encode())}


async def edit_file(sandbox: Sandbox, args: dict[str, Any]) -> dict[str, Any]:
    path = _rel(sandbox, args["path"])
    old, new = args["old_str"], args["new_str"]
    before = await sandbox.read_text(path)
    count = before.count(old)
    if count == 0:
        return {"error": "old_str not found in file"}
    if count > 1:
        return {"error": f"old_str matched {count} times; it must be unique"}
    after = before.replace(old, new, 1)
    await sandbox.write_text(path, after)
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{args['path']}",
        tofile=f"b/{args['path']}",
    )
    return {"path": args["path"], "diff": "".join(diff)}


async def search(sandbox: Sandbox, args: dict[str, Any]) -> dict[str, Any]:
    path = args.get("path") or "."
    _rel(sandbox, path)
    pattern = shlex.quote(args["pattern"])
    target = shlex.quote(path)
    glob = args.get("glob")
    rg = f"rg -n --no-heading --color never {'-g ' + shlex.quote(glob) + ' ' if glob else ''}-e {pattern} {target}"
    grep = f"grep -rn {'--include=' + shlex.quote(glob) + ' ' if glob else ''}-E -e {pattern} {target}"
    # ripgrep when present; grep -rn otherwise. Nothing is ever installed at runtime.
    cmd = f"if command -v rg >/dev/null 2>&1; then {rg}; else {grep}; fi"
    result = await sandbox.run(cmd, timeout_s=30)
    matches = [line for line in result.stdout.splitlines() if line]
    return {"matches": truncate("\n".join(matches)), "count": len(matches)}


TOOLS: dict[str, ToolFn] = {
    "bash": bash,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "search": search,
}


async def run_tool(sandbox: Sandbox, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool; any failure becomes a structured error result."""
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return await fn(sandbox, args)
    except PathEscapeError as exc:
        return {"error": str(exc)}
    except FileNotFoundError as exc:
        return {"error": f"file not found: {exc.filename or exc}"}
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"invalid arguments: {exc}"}
    except Exception as exc:  # noqa: BLE001 - tool failures must never crash the loop
        return {"error": f"{type(exc).__name__}: {exc}"}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "bash",
        "description": "Run a shell command in the workspace. Returns exit code, stdout and stderr.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "timeout_s": {"type": "integer", "default": 60}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file with line numbers. Paths are relative to the workspace.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "default": 0},
            "limit": {"type": "integer", "default": 400}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or replace a file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace exactly one occurrence of old_str with new_str. Fails on zero or multiple matches.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}},
            "required": ["path", "old_str", "new_str"]}}},
    {"type": "function", "function": {
        "name": "search",
        "description": "Search file contents with a regex (ripgrep). Returns path:line:text matches.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string", "default": "."},
            "glob": {"type": "string"}},
            "required": ["pattern"]}}},
]
