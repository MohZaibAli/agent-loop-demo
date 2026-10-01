"""Global application spend guard, persisted to SPEND_FILE with a file lock."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from agent.cost import load_config

GLOBAL_CEILING = float(load_config()["budget"]["global_ceiling_usd"])


class Budget:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.environ.get("SPEND_FILE", "./data/spend.json"))
        self.ceiling = GLOBAL_CEILING

    def _lock_path(self) -> Path:
        return self.path.with_suffix(".lock")

    def _read(self) -> float:
        try:
            return float(json.loads(self.path.read_text()).get("spent", 0.0))
        except (FileNotFoundError, ValueError):
            return 0.0

    def spent(self) -> float:
        return self._read()

    def remaining(self) -> float:
        return max(0.0, self.ceiling - self.spent())

    def can_start(self, max_cost_usd: float) -> tuple[bool, str]:
        remaining = self.remaining()
        if self.spent() >= self.ceiling:
            return False, f"global budget exhausted (${self.ceiling:.2f})"
        if max_cost_usd > remaining:
            return False, f"max_cost_usd {max_cost_usd:.2f} exceeds remaining ${remaining:.3f}"
        return True, ""

    def add(self, amount: float) -> float:
        """Atomically add spend under an exclusive file lock; returns new total."""
        if amount <= 0:
            return self.spent()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._lock_path(), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            total = self._read() + amount
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"spent": round(total, 8)}))
            os.replace(tmp, self.path)
            fcntl.flock(lock, fcntl.LOCK_UN)
        return total

    def snapshot(self) -> dict[str, float]:
        spent = self.spent()
        return {"spent": round(spent, 6), "remaining": round(max(0.0, self.ceiling - spent), 6)}
