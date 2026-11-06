"""Run a reader model over the labelled set and save its answers for the scorer.

F2 Step 3, part 2. The answers file is what `python -m webapp.reader.score` reads, so the score
can be checked again from the stored answers without the model. A first line, `{"meta": ...}`,
records what produced them: the backend, the model, the GGUF file's SHA-256 when there is one,
the prompt's SHA-256, the set's SHA-256, the seed and the time per question.

    python -m webapp.reader.run --gguf PATH --out ANSWERS.jsonl     # llama-cpp-python
    python -m webapp.reader.run --ollama qwen3:8b --out ANSWERS.jsonl   # on the Mac
    python -m webapp.reader.run --claude claude-haiku-5-5 --out ANSWERS.jsonl   # paid API

The answers keep the model's raw reading (before the check); the scorer applies the check.
A question the model could not answer is written with `"reading": null` and scored as unsure
and wrong. With a backend that keeps token counts (Claude), each line also has its `tokens`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from webapp.reader.model import (
    SEED,
    Backend,
    ClaudeBackend,
    LlamaCppBackend,
    OllamaBackend,
    raw_reading,
)
from webapp.reader.prompt import answer_schema, system_prompt
from webapp.reader.score import LABELLED_SET, load_set


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prompt_sha256() -> str:
    text = system_prompt() + json.dumps(answer_schema(), sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(backend: Backend, rows: list[dict], out: Path, meta: dict, log=sys.stderr) -> None:
    timings = []
    done = 0  # token records seen so far (a failed call leaves none)
    with out.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"meta": meta}, ensure_ascii=False) + "\n")
        for n, row in enumerate(rows, 1):
            started = time.perf_counter()
            reading = raw_reading(row["text"], backend)
            seconds = time.perf_counter() - started
            timings.append(seconds)
            line = {"id": row["id"], "reading": reading, "seconds": round(seconds, 2)}
            usage = getattr(backend, "usage", None)
            if usage is not None:
                line["tokens"] = usage[-1] if len(usage) > done else None
                done = len(usage)
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"{n}/{len(rows)} {row['id']} {seconds:.1f}s", file=log)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m webapp.reader.run")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--gguf", type=Path, help="a GGUF file, run with llama-cpp-python")
    which.add_argument("--ollama", help="an Ollama model tag, e.g. qwen3:8b")
    which.add_argument("--claude", help="a Claude model id, e.g. claude-haiku-5-5 (paid)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--set", type=Path, default=LABELLED_SET)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None, help="only the first N questions")
    args = parser.parse_args(argv)

    if args.gguf:
        backend: Backend = LlamaCppBackend(str(args.gguf), n_threads=args.threads)
        model = {"file": args.gguf.name, "sha256": sha256_file(args.gguf)}
    elif args.claude:
        backend = ClaudeBackend(model=args.claude)
        model = {"id": args.claude, "effort": backend.effort}
    else:
        backend = OllamaBackend(model=args.ollama)
        model = {"tag": args.ollama}
    rows = load_set(args.set)[: args.limit]
    meta = {
        "backend": backend.name,
        "model": model,
        "prompt_sha256": prompt_sha256(),
        "set_sha256": sha256_file(args.set),
        "seed": None if args.claude else SEED,
        "temperature": None if args.claude else 0,
        "questions": len(rows),
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    run(backend, rows, args.out, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
