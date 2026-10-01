"""Sandbox abstraction: a workspace with command execution and file I/O."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

WORKSPACE = "/home/user/workspace"


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


class Sandbox(Protocol):
    """Minimal interface shared by LocalSandbox and E2BSandbox."""

    sandbox_id: str
    workspace: str

    async def run(self, command: str, timeout_s: float = 60, cwd: str | None = None) -> CommandResult: ...
    async def read_text(self, path: str) -> str: ...
    async def write_text(self, path: str, content: str) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def kill(self) -> None: ...


class PathEscapeError(ValueError):
    """Raised when a path resolves outside the sandbox workspace."""


def resolve_in_workspace(workspace: str, path: str) -> str:
    """Resolve `path` against `workspace` and reject anything that escapes it.

    Symlinks under the workspace are followed so a link pointing outside is rejected.
    """
    root = Path(workspace).resolve()
    candidate = Path(path) if os.path.isabs(path) else root / path
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise PathEscapeError(f"path escapes workspace: {path}")
    return str(resolved)


class LocalSandbox:
    """Temporary-directory sandbox used by unit tests and SANDBOX_PROVIDER=local."""

    def __init__(self, seed_dir: str | None = None) -> None:
        self.sandbox_id = f"local_{uuid.uuid4().hex[:12]}"
        self._dir = tempfile.mkdtemp(prefix="agent-ws-")
        self.workspace = str(Path(self._dir).resolve())
        self.alive = True
        if seed_dir:
            shutil.copytree(seed_dir, self.workspace, dirs_exist_ok=True)

    @classmethod
    async def create(cls, seed_dir: str | None = None, **_: object) -> "LocalSandbox":
        return cls(seed_dir)

    def _abs(self, path: str) -> str:
        return resolve_in_workspace(self.workspace, path)

    async def run(self, command: str, timeout_s: float = 60, cwd: str | None = None) -> CommandResult:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd or self.workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return CommandResult(124, "", f"command timed out after {timeout_s}s")
        return CommandResult(proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace"))

    async def read_text(self, path: str) -> str:
        return Path(self._abs(path)).read_text()

    async def write_text(self, path: str, content: str) -> None:
        target = Path(self._abs(path))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    async def exists(self, path: str) -> bool:
        return Path(self._abs(path)).exists()

    async def kill(self) -> None:
        self.alive = False
        shutil.rmtree(self._dir, ignore_errors=True)
