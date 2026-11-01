"""Validated, logged and budgeted LLM calls (M6, Decisions 1 and 9).

`structured_call` is the only path from Warren to a model. It renders a versioned prompt, asks the
model, and validates the answer with a Pydantic model. An invalid answer is asked again with the
error, at most `ATTEMPTS` times in all; every attempt is one `llm_calls` row, and after the last
invalid one it raises `LLMRejected`: an answer is never guessed or repaired. A batch (one command)
has a token budget, read from its stored calls, and no call starts once it is spent.
"""

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from domains.llm.client import LLMClient, LLMError
from shared_kernel.config import node_model

PROMPTS_DIR = Path(__file__).parent / "prompts"
ATTEMPTS = 3
DEFAULT_BUDGET = 2_000_000  # input plus output tokens per batch
_SPLIT = "\n---- user ----\n"


class LLMRejected(RuntimeError):
    """The model gave no valid answer in `ATTEMPTS` tries."""


class BudgetSpent(RuntimeError):
    """The batch's token budget is used up; the command stops cleanly."""


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    system: str
    user: str  # a template with {slots}
    sha256: str

    def render(self, **slots: str) -> str:
        return self.user.format(**slots)


def load_prompt(name: str, version: int, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    """`<name>.v<version>.md`: the system part, a `---- user ----` line, then the user template."""
    path = prompts_dir / f"{name}.v{version}.md"
    text = path.read_text(encoding="utf-8")
    if _SPLIT not in text:
        raise ValueError(f"{path.name}: no '---- user ----' line between the two parts")
    system, user = text.split(_SPLIT, 1)
    return Prompt(name, version, system.strip(), user.strip(),
                  hashlib.sha256(text.encode()).hexdigest())  # fmt: skip


def latest_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    versions = [int(m.group(1)) for p in prompts_dir.glob(f"{name}.v*.md")
                if (m := re.fullmatch(rf"{re.escape(name)}\.v(\d+)\.md", p.name))]  # fmt: skip
    if not versions:
        raise FileNotFoundError(f"no prompt files for {name} in {prompts_dir}")
    return load_prompt(name, max(versions), prompts_dir)


def tokens_used(conn: sqlite3.Connection, batch_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM llm_calls WHERE batch_id = ?",
        (batch_id,),
    ).fetchone()
    return row[0]


@dataclass(frozen=True)
class Result:
    value: BaseModel
    call_id: int
    model: str


def _record(conn, batch_id, node, model, prompt, ref, attempt, inputs, reply, status, error):
    cur = conn.execute(
        "INSERT INTO llm_calls (batch_id, node, model, prompt_name, prompt_version, "
        "prompt_sha256, ref, attempt, input_json, output_json, status, error, input_tokens, "
        "output_tokens, latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (batch_id, node, reply.model if reply else model, prompt.name, prompt.version,
         prompt.sha256, ref, attempt, json.dumps(inputs, sort_keys=True),
         reply.raw_json if reply else None, status, error,
         reply.input_tokens if reply else 0, reply.output_tokens if reply else 0,
         reply.latency_ms if reply else 0),
    )  # fmt: skip
    conn.commit()
    return cur.lastrowid


def with_choices(schema: dict, choices: dict[str, list[str]]) -> dict:
    """A copy of `schema` where each named top-level string field may only take the given values."""
    out = {**schema, "properties": dict(schema["properties"])}
    for field, values in choices.items():
        if out["properties"].get(field, {}).get("type") != "string" or not values:
            raise ValueError(f"{field!r} is not a top-level string field, or has no values")
        out["properties"][field] = {**out["properties"][field], "enum": list(values)}
    return out


def structured_call(
    conn: sqlite3.Connection,
    client: LLMClient,
    node: str,
    prompt: Prompt,
    slots: dict[str, str],
    model_cls: type[BaseModel],
    ref: str,
    batch_id: str,
    budget: int = DEFAULT_BUDGET,
    check=None,
    choices: dict[str, list[str]] | None = None,
) -> Result:
    """Ask, validate (with `check(value)` for rules a schema can't hold), retry, log every try.

    `choices` names the allowed values of a top-level string field that is data, not code (the
    event taxonomy). They go into the schema the model answers with, as an enum, so the model
    picks from the list instead of inventing a name; `check` still rejects any other value."""
    model = node_model(node).model
    system, user = prompt.system, prompt.render(**slots)
    schema = with_choices(model_cls.model_json_schema(), choices or {})
    error = None
    for attempt in range(1, ATTEMPTS + 1):
        if tokens_used(conn, batch_id) >= budget:
            raise BudgetSpent(f"batch {batch_id} used its {budget:,} tokens")
        message = user if error is None else (
            f"{user}\n\nYour previous answer was invalid: {error}\nAnswer again, fixing that."
        )  # fmt: skip
        try:
            reply = client.call(model, system, message, schema)
        except LLMError as e:
            _record(conn, batch_id, node, model, prompt, ref, attempt, slots, None, "error", str(e))
            error = None  # nothing wrong with the answer; ask the same question again
            continue
        try:
            value = model_cls.model_validate_json(reply.raw_json)
            if check is not None:
                check(value)
        except (ValidationError, ValueError) as e:
            error = str(e).replace("\n", " ")[:1000]
            _record(conn, batch_id, node, model, prompt, ref, attempt, slots, reply, "invalid",
                    error)  # fmt: skip
            continue
        call_id = _record(conn, batch_id, node, model, prompt, ref, attempt, slots, reply, "ok",
                          None)  # fmt: skip
        return Result(value, call_id, reply.model)
    raise LLMRejected(f"{node} {ref}: no valid answer in {ATTEMPTS} attempts")
