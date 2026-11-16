"""The question reader: one question in, one checked reading out (Decision 9).

`read_question(text, today, backend)` asks a local open model for a reading held to the answer
schema, then passes it through the code check (`reading.check`). Anything that goes wrong (no
model running, a timeout, an answer that is not JSON) returns an unsure, empty reading, so the
reading card falls back to the menus; it never raises into a screen.

The model sits behind a small backend interface, so it can be swapped without touching the
screens (F2 design, "The question reader's model"):

- `OllamaBackend` talks to Ollama on the owner's Mac (`http://127.0.0.1:11434`, its native
  `/api/chat` with `format` set to the schema). Standard library only; nothing to install in
  the app.
- `ClaudeBackend` asks Claude through Anthropic's API (paid, per question; the owner approved
  testing Claude Haiku on the exam, nov.06.2026). Effort is low and the answer is held to the
  same schema by the API's structured outputs. It keeps each call's token counts, so the
  exam's cost is measured, not estimated.
- `LlamaCppBackend` loads the same GGUF file in-process with llama-cpp-python (MIT), which is
  how the exam runs on a machine without Ollama. It is a measuring tool, not an app
  dependency, so it is imported only when used and is not pinned in `requirements.txt`.

The two open-model backends run llama.cpp underneath, at temperature 0 with a fixed seed, on the
same weights. Claude's current models refuse a temperature, so none is sent.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from webapp.reader.prompt import answer_schema, system_prompt, user_message
from webapp.reader.reading import Reading, check

SEED = 7
MAX_TOKENS = 400


class Backend(Protocol):
    name: str

    def complete(self, system: str, user: str, schema: dict) -> str:
        """The model's raw answer text."""


@dataclass
class OllamaBackend:
    model: str = "qwen3:8b"
    url: str = "http://127.0.0.1:11434"
    timeout: float = 60.0
    name: str = field(default="ollama", init=False)

    def complete(self, system: str, user: str, schema: dict) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "seed": SEED, "num_predict": MAX_TOKENS},
        }
        request = urllib.request.Request(
            f"{self.url}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            return json.loads(response.read())["message"]["content"]


@dataclass
class LlamaCppBackend:
    model_path: str
    n_ctx: int = 8192
    n_threads: int | None = None
    name: str = field(default="llama-cpp-python", init=False)

    def __post_init__(self) -> None:
        from llama_cpp import Llama  # optional: only for running the exam without Ollama

        self._llm = Llama(
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            seed=SEED,
            verbose=False,
        )

    def complete(self, system: str, user: str, schema: dict) -> str:
        result = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                # Qwen3's switch for its thinking mode; the schema holds the answer to JSON anyway
                {"role": "user", "content": user + " /no_think"},
            ],
            response_format={"type": "json_object", "schema": schema},
            temperature=0,
            seed=SEED,
            max_tokens=MAX_TOKENS,
        )
        return result["choices"][0]["message"]["content"]


def closed_schema(schema):
    """`schema` in the form structured outputs accept: every object closed
    (`additionalProperties: false`), and a nullable enum written as `anyOf` a string enum or
    null. It allows exactly the same answers."""
    if isinstance(schema, list):
        return [closed_schema(v) for v in schema]
    if not isinstance(schema, dict):
        return schema
    if schema.get("type") == ["string", "null"] and "enum" in schema:
        values = [v for v in schema["enum"] if v is not None]
        return {"anyOf": [{"type": "string", "enum": values}, {"type": "null"}]}
    out = {k: closed_schema(v) for k, v in schema.items()}
    if out.get("type") == "object":
        out["additionalProperties"] = False
    return out


@dataclass
class ClaudeBackend:
    model: str = "claude-haiku-5-5"
    effort: str = "low"
    max_tokens: int = 2000
    name: str = field(default="anthropic", init=False)
    usage: list = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        import os

        import anthropic  # the engine's dependency; imported only when this backend is used

        from shared_kernel.config import anthropic_base_url

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(
            api_key=os.environ.get("WARREN_ANTHROPIC_API_KEY") or None,
            base_url=anthropic_base_url(),
            max_retries=3,
        )

    def complete(self, system: str, user: str, schema: dict) -> str:
        try:
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                # the rules are the same for every question, so they are cached after the first
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": closed_schema(schema)},
                },
            )
        except self._anthropic.APIError as e:
            raise OSError(f"{type(e).__name__}: {e}") from e
        u = msg.usage
        self.usage.append(
            {
                "input": u.input_tokens,
                "cache_write": u.cache_creation_input_tokens or 0,
                "cache_read": u.cache_read_input_tokens or 0,
                "output": u.output_tokens,
            }
        )
        return "".join(b.text for b in msg.content if b.type == "text")


def unavailable() -> Reading:
    """What the card gets when the reader cannot answer: nothing read, so the menus."""
    return Reading(kind="", unsure=True, dropped=("reader",))


def parse_answer(raw: str) -> dict | None:
    """The model's JSON object, or None. Tolerates an empty think block before it."""
    text = raw.strip()
    if "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def raw_reading(text: str, backend: Backend) -> dict | None:
    """The model's answer before the check, or None when the reader is unavailable."""
    try:
        raw = backend.complete(system_prompt(), user_message(text), answer_schema())
    except (OSError, urllib.error.URLError, TimeoutError, KeyError, ValueError):
        return None
    return parse_answer(raw)


def read_question(text: str, today: date, backend: Backend) -> Reading:
    """One question's checked reading. `today` is the last ended day (the check's limit)."""
    data = raw_reading(text, backend)
    if data is None:
        return unavailable()
    return check(Reading.from_dict(data), text, today)
