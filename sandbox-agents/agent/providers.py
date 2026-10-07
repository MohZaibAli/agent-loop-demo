"""LLM providers: ScriptedProvider (mock, $0) and OpenRouterProvider (real)."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from agent.cost import Usage, usage_from_response

DEFAULT_MODEL = "anthropic/claude-haiku-4.5"
# OpenRouter's Jev Router (typesafe/jev-router) picks a model per request based on
# the prompt. We route the first turn through it, then pin the chosen model for the
# rest of the run so Anthropic prompt caching keeps hitting. MODEL_ROUTER= disables it.
DEFAULT_ROUTER = "typesafe/jev-router"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Completion:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""  # model that actually served this turn

    def to_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.text or None}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                for c in self.tool_calls
            ]
        return msg


class Provider(Protocol):
    name: str
    model: str

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Completion: ...


class ScriptedProvider:
    """Replays fixture turns in order. Makes no network calls and costs $0."""

    name = "mock"
    model = "scripted/fixture"

    def __init__(self, turns: list[dict[str, Any]]) -> None:
        self._turns = list(turns)
        self._index = 0

    @classmethod
    def from_fixture(cls, filename: str = "scripted_fix_run.json", key: str | None = None) -> "ScriptedProvider":
        data = json.loads((FIXTURES / filename).read_text())
        turns = data[key]["turns"] if key else data["turns"]
        return cls(turns)

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Completion:
        # Optional pacing so a replayed demo reads like a model thinking (0 in tests).
        delay = float(os.environ.get("MOCK_TURN_DELAY_S", "0") or 0)
        if delay:
            await asyncio.sleep(delay)
        if self._index >= len(self._turns):
            return Completion(text="Script exhausted; stopping.")
        turn = self._turns[self._index]
        self._index += 1
        calls = [ToolCall(c["id"], c["name"], c["arguments"]) for c in turn.get("tool_calls", [])]
        return Completion(text=turn.get("text", ""), tool_calls=calls)


class OpenRouterProvider:
    """Chat completions with tool calling via OpenRouter's OpenAI-compatible API."""

    name = "openrouter"

    def __init__(self, api_key: str, model: str | None = None, router: str | None = None) -> None:
        from openai import AsyncOpenAI

        self.model = model or os.environ.get("AGENT_MODEL") or DEFAULT_MODEL
        env_router = os.environ.get("MODEL_ROUTER")
        self.router = router if router is not None else (DEFAULT_ROUTER if env_router is None else env_router)
        self.routed_model: str | None = None
        self._client = AsyncOpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

    def _request_model(self) -> str:
        """Jev on the first turn (routing on the task prompt), pinned model afterwards."""
        if self.routed_model:
            return self.routed_model
        return self.router or self.model

    @staticmethod
    def _with_cache(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Anthropic caches the prefix (tools + system) up to the breakpoint, so a
        # single cache_control on the system prompt covers the tool definitions too.
        out = []
        for m in messages:
            if m["role"] == "system" and isinstance(m["content"], str):
                m = {"role": "system", "content": [
                    {"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}]}
            out.append(m)
        return out

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Completion:
        request_model = self._request_model()
        response = await self._client.chat.completions.create(
            model=request_model,
            messages=self._with_cache(messages),
            tools=tools,
        )
        served = response.model or request_model
        if served == request_model and request_model == self.router:
            served = self.model  # router did not report the routed model; assume the default
        self.routed_model = served
        choice = response.choices[0].message
        calls = [
            ToolCall(c.id, c.function.name, _parse_args(c.function.arguments))
            for c in (choice.tool_calls or [])
        ]
        raw_usage = response.usage.model_dump() if response.usage else None
        return Completion(text=choice.content or "", tool_calls=calls,
                          usage=usage_from_response(served, raw_usage), model=served)


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_raw": raw}


def make_provider(kind: str | None = None, fixture: str = "scripted_fix_run.json",
                  fixture_key: str | None = None) -> Provider:
    """Build a provider by name. 'mock' never touches the network."""
    kind = (kind or os.environ.get("LLM_PROVIDER") or "mock").lower()
    if kind == "mock":
        return ScriptedProvider.from_fixture(fixture, fixture_key)
    if kind == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is required for LLM_PROVIDER=openrouter")
        return OpenRouterProvider(key)
    raise ValueError(f"unknown LLM_PROVIDER: {kind}")
