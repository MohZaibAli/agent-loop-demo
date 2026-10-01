"""Token usage and cost accounting."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@lru_cache
def load_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_PATH.read_text())


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0

    def add(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cached_tokens += other.cached_tokens
        self.total_tokens += other.total_tokens
        self.cost += other.cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.total_tokens,
            "cost": round(self.cost, 6),
        }


def price_from_tokens(model: str, prompt: int, completion: int, cached: int = 0) -> float | None:
    """Compute cost from config.yaml prices; None when the model is not priced."""
    prices = load_config()["models"].get(model)
    if not prices:
        return None
    uncached = max(0, prompt - cached)
    return (
        uncached * prices["prompt"]
        + cached * prices.get("input_cache_read", prices["prompt"])
        + completion * prices["completion"]
    )


def usage_from_response(model: str, raw: dict[str, Any] | None) -> Usage:
    """Build Usage from an OpenRouter usage object, preferring its accounted cost."""
    if not raw:
        return Usage()
    prompt = int(raw.get("prompt_tokens") or 0)
    completion = int(raw.get("completion_tokens") or 0)
    cached = int((raw.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    total = int(raw.get("total_tokens") or prompt + completion)
    cost = raw.get("cost")
    if cost is None:
        cost = price_from_tokens(model, prompt, completion, cached)
    if cost is None:
        raise ValueError(f"no cost in response and no price configured for {model}")
    return Usage(prompt, completion, cached, total, float(cost))
