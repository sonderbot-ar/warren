"""The about-the-company check, scored against M5's labelled headlines (M6 Step 4).

The same question extraction asks per headline ("is the company the subject?") is put to every
headline of the labelled draws in `domains/news/match_sample.csv`, in batches per company. The
labels are never shown to the model. The score sets the model's precision next to the headline
rule's own on the same rows, so a gain is measured, not assumed.
"""

import sqlite3
from collections import defaultdict

from pydantic import BaseModel, ConfigDict

from domains.llm import calls
from domains.llm.client import LLMClient
from domains.llm.extract import HeadlineAbout, company
from domains.news.report import wilson

NODE = "check_headlines"
PROMPT = "check_headlines"
BATCH = 20
RULE_DRAW = "20261031"  # the draw taken with the headline rule (M5 Step 6c)


class HeadlineChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headlines: list[HeadlineAbout]


def _checker(ids: list[str]):
    def check(value: HeadlineChecks) -> None:
        if sorted(h.id for h in value.headlines) != sorted(ids):
            raise ValueError(f"headlines must list each of {', '.join(ids)} once")

    return check


def unique_headlines(rows: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """(article_id, title) per ticker, each article once, in file order."""
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    seen = set()
    for r in rows:
        if (r["ticker"], r["article_id"]) not in seen:
            seen.add((r["ticker"], r["article_id"]))
            out[r["ticker"]].append((r["article_id"], r["title"]))
    return out


def check_headlines(
    conn: sqlite3.Connection,
    client: LLMClient,
    rows: list[dict],
    batch_id: str = "check_headlines",
    budget: int = calls.DEFAULT_BUDGET,
) -> tuple[int, int]:
    """Ask about every labelled headline not yet checked with this prompt and model.

    Returns (headlines answered, batches rejected). A batch with no valid answer after the retries
    stores nothing and is asked again on the next run, like a failed classification (M6 Step 8)."""
    prompt = calls.latest_prompt(PROMPT)
    model = calls.node_model(NODE).model
    added = failed = 0
    for ticker, items in unique_headlines(rows).items():
        co = company(conn, ticker)
        done = {r[0] for r in conn.execute(
            "SELECT article_id FROM headline_checks WHERE cik = ? AND variant = 'named' AND "
            "model = ? AND prompt_sha256 = ?", (co.cik, model, prompt.sha256))}  # fmt: skip
        todo = [i for i in items if i[0] not in done]
        for start in range(0, len(todo), BATCH):
            batch = todo[start : start + BATCH]
            ids = [f"h{n}" for n in range(1, len(batch) + 1)]
            slots = {
                "company": f"{co.name} ({co.ticker})",
                "headlines": "\n".join(f"{i} | {t}" for i, (_, t) in zip(ids, batch, strict=True)),
            }
            try:
                result = calls.structured_call(
                    conn, client, NODE, prompt, slots, HeadlineChecks,
                    f"{ticker}:{batch[0][0]}", batch_id, budget, _checker(ids),
                )  # fmt: skip
            except calls.LLMRejected:
                failed += 1
                continue
            answer = {h.id: h.about for h in result.value.headlines}
            conn.executemany(
                "INSERT INTO headline_checks (article_id, cik, variant, model, prompt_sha256, "
                "call_id, about) VALUES (?, ?, 'named', ?, ?, ?, ?)",
                [(a, co.cik, model, prompt.sha256, result.call_id, int(answer[i]))
                 for i, (a, _) in zip(ids, batch, strict=True)],
            )  # fmt: skip
            conn.commit()
            added += len(batch)
    return added, failed


def _rate(k: int, n: int) -> dict:
    low, high = wilson(k, n)
    return {"k": k, "n": n, "share": k / n if n else None, "low": low, "high": high}


def score(rows: list[dict], answers: dict[tuple[str, str], bool]) -> list[dict]:
    """Per company and pooled ("all"), for each labeller ("first", "second"):

    - rule_precision: on the rule draw's `org_exact` rows, the share labelled `about`;
    - model_precision: of those rows the model calls about, the share labelled `about`;
    - recall: of the rule draw's `org_exact` rows labelled `about`, the share the model keeps;
    - dropped_about: of the rule draw's `org_exact_dropped` rows, how many the model calls about,
      and how many of those are labelled `about` (stories the word rule loses).

    `answers` maps (ticker, article_id) to the model's answer; rows without one are left out.
    """
    out = []
    for labeller, column in (("first", "label"), ("second", "second_label")):
        kept = [r for r in rows if r["draw"] == RULE_DRAW and r[column] in ("about", "related",
                "not") and (r["ticker"], r["article_id"]) in answers]  # fmt: skip
        for ticker in sorted({r["ticker"] for r in kept}) + ["all"]:
            mine = [r for r in kept if ticker in ("all", r["ticker"])]
            exact = [r for r in mine if r["method"] == "org_exact"]
            dropped = [r for r in mine if r["method"] == "org_exact_dropped"]
            said = [r for r in exact if answers[(r["ticker"], r["article_id"])]]
            about = [r for r in exact if r[column] == "about"]
            rescued = [r for r in dropped if answers[(r["ticker"], r["article_id"])]]
            out.append({
                "labeller": labeller, "ticker": ticker,
                "rule_precision": _rate(len(about), len(exact)),
                "model_precision": _rate(sum(r[column] == "about" for r in said), len(said)),
                "recall": _rate(sum(answers[(r["ticker"], r["article_id"])] for r in about),
                                len(about)),
                "dropped_called_about": len(rescued),
                "dropped_called_about_labelled_about": sum(r[column] == "about" for r in rescued),
                "dropped": len(dropped),
            })  # fmt: skip
    return out


def stored_answers(conn: sqlite3.Connection) -> dict[tuple[str, str], bool]:
    """The latest prompt's named answers, by (ticker, article_id)."""
    prompt = calls.latest_prompt(PROMPT)
    model = calls.node_model(NODE).model
    return {
        (r["ticker"], r["article_id"]): bool(r["about"])
        for r in conn.execute(
            "SELECT c.ticker, h.article_id, h.about FROM headline_checks h "
            "JOIN companies c USING (cik) WHERE h.variant = 'named' AND h.model = ? "
            "AND h.prompt_sha256 = ?",
            (model, prompt.sha256),
        )
    }
