"""Score a question reader against the labelled set, and say whether it clears the bar.

F2 Step 3 (`docs/designs/f2-web-app.md`). The bar is fixed here, in code, before any model is
run against the set, so a model is never judged by a bar moved to fit it. Every answer goes
through the same code check a student's reading goes through (`reading.check`), so the score is
the score of what a student would see.

Run: `python -m webapp.reader.score --answers ANSWERS.jsonl [--today YYYY-MM-DD] [--json]`.
ANSWERS has one line per question: {"id": "q001", "reading": {...}}. A question with no answer
counts as unsure and wrong (the reader was unavailable, so the student gets the menus).
Exit status 0 when the bar is cleared, 1 when not.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from shared_kernel.calendar import last_ended_day
from webapp.reader.reading import Reading, check, normalise

LABELLED_SET = Path(__file__).parent / "labelled_set.jsonl"

# Set nov.05.2026, before any model was run. Shares of all questions unless named otherwise.
BAR = {
    "kind": 0.95,  # the kind right (and, when out of scope, the reason)
    "companies": 0.95,  # exactly the companies named
    "date": 0.95,  # the as-of date and the period span both right
    "inputs": 0.90,  # exactly the inputs, with how, direction, value and transmission
    "kind_each_language": 0.90,  # the kind right in Spanish and in English, separately
    "wrong_unflagged_max": 0.02,  # a wrong reading shown without the unsure flag
    "unsure_max": 0.15,  # unsure readings send the student to the menus; few, or it is menus first
}
FIELDS = ("kind", "companies", "date", "inputs")


def load_set(path: Path = LABELLED_SET) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _inputs_key(reading: Reading) -> list[tuple]:
    return sorted(
        (
            i.name,
            i.how,
            i.direction,
            normalise(i.value_text) if i.value_text else None,
            i.via,
        )
        for i in reading.inputs
    )


def compare(got: Reading, expected: Reading) -> dict[str, bool]:
    """Which fields of a checked reading match the label."""
    period = (normalise(got.period) if got.period else None) == (
        normalise(expected.period) if expected.period else None
    )
    return {
        "kind": got.kind == expected.kind and got.out_of_scope == expected.out_of_scope,
        "companies": got.companies == expected.companies,
        "date": got.as_of == expected.as_of and period,
        "inputs": _inputs_key(got) == _inputs_key(expected),
    }


def score(rows: Iterable[dict], answers: Mapping[str, dict], today: date) -> dict:
    """The report: per question, per language and overall, and the bar's verdict."""
    per_question = []
    for row in rows:
        expected = check(Reading.from_dict(row["expected"]), row["text"], today)
        raw = answers.get(row["id"])
        if raw is None:
            got, fields, missing = None, dict.fromkeys(FIELDS, False), True
        else:
            got = check(Reading.from_dict(raw), row["text"], today)
            fields, missing = compare(got, expected), False
        right = all(fields.values())
        unsure = missing or got.unsure
        per_question.append(
            {
                "id": row["id"],
                "lang": row["lang"],
                "fields": fields,
                "right": right,
                "unsure": unsure,
                "missing": missing,
                "dropped": list(got.dropped) if got else [],
                "reading": got.to_dict() if got else None,
            }
        )

    def shares(items: list[dict]) -> dict:
        n = len(items)
        out = {f: sum(q["fields"][f] for q in items) / n for f in FIELDS}
        out["right"] = sum(q["right"] for q in items) / n
        out["unsure"] = sum(q["unsure"] for q in items) / n
        out["wrong_unflagged"] = sum(not q["right"] and not q["unsure"] for q in items) / n
        out["n"] = n
        return out

    overall = shares(per_question)
    by_language = {
        lang: shares([q for q in per_question if q["lang"] == lang])
        for lang in sorted({q["lang"] for q in per_question})
    }
    checks = {f: overall[f] >= BAR[f] for f in FIELDS}
    checks["kind_each_language"] = all(
        s["kind"] >= BAR["kind_each_language"] for s in by_language.values()
    )
    checks["wrong_unflagged_max"] = overall["wrong_unflagged"] <= BAR["wrong_unflagged_max"]
    checks["unsure_max"] = overall["unsure"] <= BAR["unsure_max"]
    return {
        "today": today.isoformat(),
        "bar": BAR,
        "overall": overall,
        "by_language": by_language,
        "checks": checks,
        "passes": all(checks.values()),
        "questions": per_question,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m webapp.reader.score")
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--set", type=Path, default=LABELLED_SET)
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    today = args.today or last_ended_day(datetime.now(UTC))
    with args.answers.open(encoding="utf-8") as handle:
        answers = {}
        for line in handle:
            if line.strip():
                item = json.loads(line)
                answers[item["id"]] = item["reading"]
    report = score(load_set(args.set), answers, today)
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        for name, value in report["overall"].items():
            print(f"{name:>16}: {value:.3f}" if name != "n" else f"{name:>16}: {value}")
        for lang, s in report["by_language"].items():
            print(f"{'kind (' + lang + ')':>16}: {s['kind']:.3f}  (n={s['n']})")
        for name, ok in report["checks"].items():
            print(f"{'PASS' if ok else 'FAIL'} {name} (bar {BAR[name]})")
        print("CLEARS THE BAR" if report["passes"] else "DOES NOT CLEAR THE BAR")
    return 0 if report["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
