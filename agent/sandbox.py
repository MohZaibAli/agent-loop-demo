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


# --- E2B ---------------------------------------------------------------------

E2B_TEMPLATE = os.environ.get("E2B_TEMPLATE", "agent-loop-py312")
SEED_DIR = str(Path(__file__).resolve().parents[1] / "seed_repo")


class E2BSandbox:
    """One isolated E2B microVM per run, created from the custom template."""

    workspace = WORKSPACE

    def __init__(self, inner: object) -> None:
        self._sb = inner
        self.sandbox_id: str = inner.sandbox_id  # type: ignore[attr-defined]
        self.alive = True

    @classmethod
    async def create(cls, seed_dir: str | None = SEED_DIR, ttl_s: int = 900, **_: object) -> "E2BSandbox":
        from e2b import AsyncSandbox

        # No internet inside the sandbox; the template already has python, pytest and rg.
        inner = await AsyncSandbox.create(template=E2B_TEMPLATE, timeout=ttl_s, allow_internet_access=False)
        sandbox = cls(inner)
        try:
            if seed_dir:
                await sandbox._upload_tree(seed_dir)
        except Exception:
            await sandbox.kill()
            raise
        return sandbox

    async def _upload_tree(self, seed_dir: str) -> None:
        """Ship the seed repo as one tarball and unpack it in the workspace."""
        import io
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for p in Path(seed_dir).rglob("*"):
                if "__pycache__" in p.parts or p.name.endswith(".pyc"):
                    continue
                tar.add(p, arcname=str(p.relative_to(seed_dir)))
        await self._sb.files.make_dir(self.workspace)
        await self._sb.files.write("/tmp/seed.tgz", buf.getvalue())
        res = await self._sb.commands.run(f"tar xzf /tmp/seed.tgz -C {self.workspace} && rm /tmp/seed.tgz")
        if res.exit_code != 0:
            raise RuntimeError(f"seed upload failed: {res.stderr}")

    def _abs(self, path: str) -> str:
        return resolve_in_workspace(self.workspace, path)

    async def run(self, command: str, timeout_s: float = 60, cwd: str | None = None) -> CommandResult:
        from e2b import CommandExitException, TimeoutException

        try:
            res = await self._sb.commands.run(command, cwd=cwd or self.workspace, timeout=timeout_s)
            return CommandResult(res.exit_code, res.stdout, res.stderr)
        except CommandExitException as exc:
            return CommandResult(exc.exit_code, exc.stdout, exc.stderr)
        except TimeoutException:
            return CommandResult(124, "", f"command timed out after {timeout_s}s")

    async def read_text(self, path: str) -> str:
        from e2b import NotFoundException

        target = self._abs(path)
        try:
            return await self._sb.files.read(target)
        except NotFoundException as exc:
            raise FileNotFoundError(target) from exc

    async def write_text(self, path: str, content: str) -> None:
        await self._sb.files.write(self._abs(path), content)

    async def exists(self, path: str) -> bool:
        return await self._sb.files.exists(self._abs(path))

    async def kill(self) -> None:
        self.alive = False
        try:
            await self._sb.kill()
        except Exception:  # noqa: BLE001 - already dead sandboxes are fine
            pass


def sandbox_provider() -> str:
    return (os.environ.get("SANDBOX_PROVIDER") or "e2b").lower()


async def create_sandbox(seed_dir: str | None = SEED_DIR, ttl_s: int = 900) -> Sandbox:
    """Create a sandbox for one run according to SANDBOX_PROVIDER."""
    if sandbox_provider() == "local":
        return await LocalSandbox.create(seed_dir=seed_dir)
    return await E2BSandbox.create(seed_dir=seed_dir, ttl_s=ttl_s)
