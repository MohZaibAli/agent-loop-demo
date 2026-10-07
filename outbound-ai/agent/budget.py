"""Global spend guard persisted to SPEND_FILE under a file lock."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from agent.config import load_config


class Budget:
    def __init__(self, path: str | None = None, ceiling: float | None = None) -> None:
        cfg = load_config()
        self.path = Path(path or os.environ.get("SPEND_FILE", "./data/spend.json"))
        self.ceiling = float(ceiling if ceiling is not None else cfg["budget"]["global_ceiling_usd"])
        self.costs = cfg["costs"]

    def sms_cost(self) -> float:
        return float(self.costs["sms_usd"])

    def call_cost(self, minutes: float | None = None) -> float:
        mins = float(minutes if minutes is not None else self.costs["call_estimate_minutes"])
        return round(mins * float(self.costs["call_per_minute_usd"]), 6)

    def estimate_lead(self) -> float:
        return round(self.sms_cost() + self.call_cost(), 6)

    def _read(self) -> float:
        try:
            return float(json.loads(self.path.read_text()).get("spent", 0.0))
        except (FileNotFoundError, ValueError):
            return 0.0

    def spent(self) -> float:
        return self._read()

    def remaining(self) -> float:
        return max(0.0, self.ceiling - self.spent())

    def can_start(self, estimate: float) -> tuple[bool, str]:
        if self.spent() >= self.ceiling:
            return False, f"global budget exhausted (${self.ceiling:.2f})"
        if estimate > self.remaining():
            return False, f"estimated ${estimate:.3f} exceeds remaining ${self.remaining():.3f}"
        return True, ""

    def add(self, amount: float) -> float:
        if amount <= 0:
            return self.spent()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            total = self._read() + amount
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"spent": round(total, 8)}))
            os.replace(tmp, self.path)
            fcntl.flock(lock, fcntl.LOCK_UN)
        return total

    def snapshot(self) -> dict[str, float]:
        spent = self.spent()
        return {"spent": round(spent, 6), "remaining": round(max(0.0, self.ceiling - spent), 6),
                "ceiling": self.ceiling}
