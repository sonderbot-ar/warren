"""The one door to a language model (M6, Decision 11 guardrail 1: sources behind adapters).

`LLMClient.call` sends a system prompt and a user message and returns one JSON object shaped by a
schema. `AnthropicClient` asks Claude through forced tool use; `FakeClient` replays answers for
tests, so CI never needs a key. Nothing here validates or stores: that is `calls.structured_call`.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Reply:
    raw_json: str  # the model's answer, as JSON text
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class LLMError(RuntimeError):
    """The model could not be reached or did not answer (network, rate limit, server error)."""


class LLMClient(Protocol):
    def call(self, model: str, system: str, user: str, schema: dict) -> Reply: ...


class AnthropicClient:
    """Claude through the Anthropic SDK; the key comes from `shared_kernel.config` only."""

    TOOL = "answer"

    def __init__(self, api_key: str, max_tokens: int = 2048):
        import anthropic  # imported here so the rest of Warren runs without the SDK

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=3)
        self.max_tokens = max_tokens

    def call(self, model: str, system: str, user: str, schema: dict) -> Reply:
        start = time.monotonic()
        try:
            msg = self._client.messages.create(
                model=model,
                max_tokens=self.max_tokens,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[{"name": self.TOOL, "description": "The answer.", "input_schema": schema}],
                tool_choice={"type": "tool", "name": self.TOOL},
            )
        except self._anthropic.APIError as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e
        latency = int((time.monotonic() - start) * 1000)
        answer = next((b.input for b in msg.content if b.type == "tool_use"), None)
        return Reply(
            json.dumps(answer) if answer is not None else "",
            msg.model,
            msg.usage.input_tokens,
            msg.usage.output_tokens,
            latency,
        )


class FakeClient:
    """Answers from a list (in order) or a function of (system, user); records every request."""

    def __init__(self, answers: list | Callable[[str, str], object], tokens: tuple = (100, 20)):
        self._answers = answers if callable(answers) else iter(answers)
        self.tokens = tokens
        self.requests: list[dict] = []

    def call(self, model: str, system: str, user: str, schema: dict) -> Reply:
        self.requests.append({"model": model, "system": system, "user": user, "schema": schema})
        answer = self._answers(system, user) if callable(self._answers) else next(self._answers)
        if isinstance(answer, Exception):
            raise answer
        raw = answer if isinstance(answer, str) else json.dumps(answer)
        return Reply(raw, model, self.tokens[0], self.tokens[1], 0)
