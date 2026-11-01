"""What the LLM steps did, per case and variant, and what they cost (M6 Step 7).

Read from the stored rows only, so the report can be written again at any time without a call.
"""

import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from domains.llm import headlines, propose
from domains.llm.extract import choose_events, window_start
from domains.news.report import read_sample
from shared_kernel.config import NODE_MODELS

CAVEAT = (
    "Masking reduces what the model can recall about what happened next; it does not remove it. "
    "A model can recover a masked company and date from small clues, so the gap between the "
    "named and masked results is not, on its own, a measure of look-ahead."
)


def _pct(rate: dict) -> str:
    if not rate["n"]:
        return "–"
    return f"{rate['share']:.2f} ({rate['low']:.2f}–{rate['high']:.2f}, n={rate['n']})"


def case_rows(conn: sqlite3.Connection) -> list[dict]:
    """Per case and variant, with the current models, prompts and event choice only: rows stored
    by an earlier prompt version or an earlier choice stay in the database, for the record, and
    are left out here."""
    _, _, x_model, x_sha = propose.current_keys()
    out = []
    for s in conn.execute("SELECT * FROM case_llm_status ORDER BY case_id, variant"):
        cls = conn.execute(
            "SELECT c.status, c.event_type, e.event_id, e.source_count, e.first_seen, e.last_seen, "
            "r.as_of, r.tz FROM event_classifications c JOIN events e USING (event_id) "
            "JOIN event_runs r ON r.event_run_id = e.event_run_id WHERE e.event_run_id = ? "
            "AND c.variant = ? AND c.model = ? AND c.prompt_sha256 = ?",
            (s["event_run_id"], s["variant"], x_model, x_sha),
        ).fetchall()
        if cls:  # the events chosen for the case window now, not an earlier choice's
            start = window_start(date.fromisoformat(cls[0]["as_of"]), ZoneInfo(cls[0]["tz"]))
            chosen = {e["event_id"] for e in choose_events([dict(c) for c in cls], start)}
            cls = [c for c in cls if c["event_id"] in chosen]
        current = propose.current_set(conn, s["case_id"], s["variant"])
        set_ids = [current["set_id"]] if current is not None else []
        proposals = conn.execute(
            "SELECT status, clipped, sigma_flag FROM shock_proposals WHERE set_id IN "
            f"({','.join('?' * len(set_ids))})", set_ids,
        ).fetchall() if set_ids else []  # fmt: skip
        sets = [current] if current is not None else []
        types = Counter(c["event_type"] for c in cls if c["status"] == "ok")
        out.append({
            "case_id": s["case_id"], "variant": s["variant"], "events": s["events_total"],
            "chosen": s["events_chosen"], "ok": sum(c["status"] == "ok" for c in cls),
            "failed": sum(c["status"] == "failed" for c in cls), "types": types,
            "macro": types.get("macro", 0),
            "sets": "; ".join("failed" if x["status"] == "failed" else
                              ("no impact" if x["no_impact"] else "ok") for x in sets) or "–",
            "proposals": Counter(p["status"] for p in proposals),
            "clipped": sum(p["clipped"] for p in proposals),
            "flags": Counter(p["sigma_flag"] for p in proposals if p["sigma_flag"]),
        })  # fmt: skip
    return out


def tokens(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every call ever made, by node, model and prompt version: what was spent, and on what."""
    return conn.execute(
        "SELECT node, model, prompt_version, COUNT(*) AS calls, SUM(status = 'ok') AS ok, "
        "SUM(status = 'invalid') AS invalid, SUM(status = 'error') AS errors, "
        "SUM(input_tokens) AS input, SUM(output_tokens) AS output FROM llm_calls "
        "GROUP BY node, model, prompt_version ORDER BY node, model, prompt_version"
    ).fetchall()


def agreement(conn: sqlite3.Connection) -> tuple[int, int]:
    """Events classified ok in both variants with the current model and extraction prompt, and
    how many agree on type."""
    _, _, x_model, x_sha = propose.current_keys()
    row = conn.execute(
        "SELECT COUNT(*), SUM(n.event_type = m.event_type) FROM event_classifications n "
        "JOIN event_classifications m ON m.event_id = n.event_id AND m.model = n.model "
        "AND m.prompt_sha256 = n.prompt_sha256 AND m.variant = 'masked' "
        "WHERE n.variant = 'named' AND n.status = 'ok' AND m.status = 'ok' AND n.model = ? "
        "AND n.prompt_sha256 = ?",
        (x_model, x_sha),
    ).fetchone()
    return row[0], row[1] or 0


def write_report(
    conn: sqlite3.Connection, path: Path, sample_rows: list[dict] | None = None
) -> str:
    rows = case_rows(conn)
    lines = ["# LLM steps (M6)", "", "## Cases", "",
             "| Case | Variant | Events (chosen) | Classified ok / failed | Macro | Types | "
             "Proposal set | Proposals | Clipped | σ flags |",
             "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in rows:
        types = ", ".join(f"{t} {n}" for t, n in sorted(r["types"].items())) or "–"
        props = ", ".join(f"{s} {n}" for s, n in sorted(r["proposals"].items())) or "–"
        flags = ", ".join(f"{s} {n}" for s, n in sorted(r["flags"].items())) or "–"
        lines.append(f"| {r['case_id']} | {r['variant']} | {r['events']} ({r['chosen']}) | "
                     f"{r['ok']} / {r['failed']} | {r['macro']} | {types} | {r['sets']} | "
                     f"{props} | {r['clipped']} | {flags} |")  # fmt: skip
    both, same = agreement(conn)
    lines += ["", "## Named and masked", "",
              f"Events classified in both variants: {both}; same type: {same}.", "", CAVEAT, "",
              "Training cutoffs: " + ", ".join(
                  f"{m.model} {m.training_cutoff or 'not yet recorded'}"
                  for m in {v.model: v for v in NODE_MODELS.values()}.values()),
              ]  # fmt: skip
    lines += ["", "## Calls and tokens", "",
              "Every call made, including those of earlier prompt versions; the tables above use "
              "the current prompts only.", "",
              "| Node | Model | Prompt version | Calls | ok / invalid / error | Input tokens | "
              "Output tokens |", "|---|---|---|---|---|---|---|"]  # fmt: skip
    for t in tokens(conn):
        lines.append(f"| {t['node']} | {t['model']} | v{t['prompt_version']} | {t['calls']} | "
                     f"{t['ok']} / {t['invalid']} / {t['errors']} | {t['input']:,} | "
                     f"{t['output']:,} |")  # fmt: skip
    answers = headlines.stored_answers(conn)
    sample = sample_rows if sample_rows is not None else read_sample()
    if answers and sample:
        lines += ["", "## About-the-company check against the labelled headlines", "",
                  f"Draw {headlines.RULE_DRAW} (taken with the headline rule), `org_exact` rows. "
                  "Rule precision is the share labelled about among the rows the rule passed; "
                  "model precision the same among the rows the model also calls about.", "",
                  "| Labeller | Company | Rule precision | Model precision | Recall | "
                  "Dropped rows called about (labelled about) |",
                  "|---|---|---|---|---|---|"]  # fmt: skip
        for s in headlines.score(sample, answers):
            lines.append(f"| {s['labeller']} | {s['ticker']} | {_pct(s['rule_precision'])} | "
                         f"{_pct(s['model_precision'])} | {_pct(s['recall'])} | "
                         f"{s['dropped_called_about']} of {s['dropped']} "
                         f"({s['dropped_called_about_labelled_about']}) |")  # fmt: skip
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text
