"""The pipeline report (M7): one Markdown file per pipeline run.

Sections 1–5 are rendered from the pipeline's final state and the database alone, so they render
to the same text every time and `reproduce` compares them. Section 6, the trace, comes after
`text.TRACE_MARKER` and reads the telemetry file (timings change on every run).
"""

import json
import sqlite3
from pathlib import Path

from domains.analysis import report as dcf_report
from domains.analysis.montecarlo import BAND_NOTE, LINES, RATES_CLEAN, load_bands
from domains.news.gdelt import known_by
from domains.news.store import iso
from domains.orchestration import text
from domains.orchestration.state import PipelineState
from domains.orchestration.telemetry import Emitter

HEADLINES_PER_EVENT = 5


def _m(value: float) -> str:
    return f"{value / 1e6:,.0f}"


def no_shock_reason(conn: sqlite3.Connection, set_id: int | None) -> str:
    if set_id is None:
        return "no_events"
    s = conn.execute("SELECT * FROM proposal_sets WHERE set_id = ?", (set_id,)).fetchone()
    if s["status"] == "failed":
        return "failed"
    if s["no_impact"]:
        return "no_impact"
    statuses = {r[0] for r in conn.execute(
        "SELECT status FROM shock_proposals WHERE set_id = ?", (set_id,))}  # fmt: skip
    return "unreviewed" if "proposed" in statuses else "rejected"


def _headlines(conn: sqlite3.Connection, event_id: str, cutoff: str) -> list[str]:
    rows = conn.execute(
        "SELECT MIN(s.seen_at) AS seen, s.title FROM event_articles a "
        "JOIN article_sightings s USING (article_id) WHERE a.event_id = ? AND s.seen_at < ? "
        "AND s.title IS NOT NULL GROUP BY a.article_id ORDER BY seen, a.article_id LIMIT ?",
        (event_id, cutoff, HEADLINES_PER_EVENT),
    ).fetchall()
    return [f"{r['seen'][:10]} · {r['title']}" for r in rows]


def _review_note(row: sqlite3.Row, state: PipelineState) -> str:
    when = row["reviewed_at"]
    if row["status"] == "proposed" or when is None:
        return ""
    notes = []
    if when < iso(state.started_at):
        notes.append(text.INHERITED.format(when=when))
    if row["reviewer"] != "none" and when[:10] > state.as_of.isoformat():
        notes.append(text.HINDSIGHT.format(when=when[:10]))
    return "; ".join(notes)


def render(conn: sqlite3.Connection, state: PipelineState) -> str:
    """Sections 1–5, from the state and the database only."""
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (state.run_id,)).fetchone()
    vps = conn.execute(
        "SELECT value FROM run_outputs WHERE run_id = ? AND name = 'value_per_share'",
        (state.run_id,),
    ).fetchone()
    sims = {v: s for v, s in state.sim.items() if s is not None}
    currency = None
    if sims:
        currency = conn.execute("SELECT currency FROM simulations WHERE sim_id = ?",
                                (next(iter(sims.values())).sim_id,)).fetchone()[0]  # fmt: skip
    lines = [
        f"# {state.company} ({state.ticker}) as of {state.as_of.isoformat()}",
        "",
        f"Pipeline `{state.pipeline_id}` · baseline run `{state.run_id}` · seed {state.seed} · "
        f"{state.n_samples:,} samples · review {state.review}",
        "",
        "## 1. Value per share",
        "",
        text.RANGE,
        "",
        *[f"- {text.VARIANTS[v]}" for v in state.variants],
        "",
        text.SAME_SEED,
        "",
        "| | Baseline | p10 | p50 | p90 |",
        "|---|---|---|---|---|",
        f"| Baseline | {vps['value']:,.2f} | | | |",
    ]
    reasons = {}
    for v in state.variants:
        s = state.sim.get(v)
        if s is None:
            reasons[v] = no_shock_reason(conn, state.proposal_set.get(v))
            lines.append(f"| {v} | {vps['value']:,.2f} | (no shock) | | |")
        else:
            lines.append(f"| {v} | {vps['value']:,.2f} | {s.p10:,.2f} | {s.p50:,.2f} | "
                         f"{s.p90:,.2f} |")  # fmt: skip
    lines.append("")
    for v, why in reasons.items():
        lines.append(f"- {v}: " + text.NO_SHOCK_LINE.format(why=text.NO_SHOCK[why]))
    for v, s in sims.items():
        notes = conn.execute("SELECT notes FROM simulations WHERE sim_id = ?", (s.sim_id,))
        stored = [n for n in (notes.fetchone()[0] or "").split("\n") if n]
        warnings = [n for n in stored if n not in (BAND_NOTE, RATES_CLEAN)]
        lines += [f"- {v} simulation warning: {w}" for w in warnings]
    if run["notes"]:
        lines += [*([""] if lines[-1] else []), "Baseline notes:", "",
                  *[f"- {n}" for n in run["notes"].split("\n") if n]]  # fmt: skip

    lines += ["", "## 2. Paths", ""]
    if not sims:
        lines.append("No variant has a shock, so the paths are the baseline's (section 5).")
    for v, s in sims.items():
        bands = load_bands(conn, s.sim_id)
        periods = sorted({p for (name, p) in bands if name == "revenue"},
                         key=lambda p: (p.startswith("Y"), p))  # fmt: skip
        for line in LINES:
            lines += [
                f"### {text.LINE_LABELS[line]}, {v} ({currency} millions)",
                "",
                "| Period | Baseline | p10 | p50 | p90 |",
                "|---|---|---|---|---|",
                *[
                    f"| {p} | {_m(bands[(line, p)].baseline)} | {_m(bands[(line, p)].p10)} | "
                    f"{_m(bands[(line, p)].p50)} | {_m(bands[(line, p)].p90)} |"
                    for p in periods
                ],
                "",
            ]

    lines += ["## 3. Shocks and their evidence", ""]
    cutoff = iso(known_by(state.as_of))
    any_shock = False
    for v in state.variants:
        set_id = state.proposal_set.get(v)
        if set_id is None:
            continue
        rows = conn.execute(
            "SELECT * FROM shock_proposals WHERE set_id = ? ORDER BY proposal_id", (set_id,)
        ).fetchall()
        for r in rows:
            any_shock = True
            unit = text.DRIVER_UNITS.get(r["driver"], "pts")
            note = _review_note(r, state)
            lines += [
                f"### {v}: {r['driver']} {r['direction']}, {r['size']}, {r['duration']}",
                "",
                f"- low / base / high: {r['low']:g} / {r['base']:g} / {r['high']:g} {unit}, from "
                f"quarter {r['start_quarter']}, {r['horizon']} quarters, decay {r['decay']:g}",
                f"- review: {r['status']} by {r['reviewer'] or '-'}"
                + (f" ({note})" if note else ""),
                f"- why: {r['rationale']} (σ {r['sigma']:.2f} {unit}"
                + (f", {r['sigma_flag']}" if r["sigma_flag"] else "")
                + (", clipped to stay in bounds" if r["clipped"] else "")
                + ")",
                "- evidence:",
            ]
            for event_id in json.loads(r["evidence_json"]):
                lines.append(f"  - event `{event_id}`")
                lines += [f"    - {h}" for h in _headlines(conn, event_id, cutoff)]
            lines.append("")
    if not any_shock:
        lines += ["No shock was proposed.", ""]

    lines += [
        "## 4. News used",
        "",
        "- files in the 7-day window: "
        + (", ".join(f"{k} {n}" for k, n in sorted(state.news_files.items())) or "none"),
        f"- articles about the company: {state.articles_kept}",
        f"- events: {state.events_total} as of the date, {state.events_chosen} in the window "
        "with two or more sources (up to 15 are read)",
        *[
            f"- classified ({v}): {c['ok']} of {c['events']}, {c['failed']} failed, "
            f"{c['not_about_company']} not about the company"
            for v, c in state.classified.items()
        ],
        "",
        "## 5. Assumptions with sources",
        "",
    ]
    baseline = dcf_report.render(conn, state.run_id).splitlines()
    lines += ["#" + ln if ln.startswith("#") else ln for ln in baseline[1:]]
    return "\n".join(lines).rstrip() + "\n"


def trace(state: PipelineState, telemetry_path: Path) -> str:
    lines = [
        "",
        text.TRACE_MARKER,
        "",
        "## 6. Trace",
        "",
        f"- checkpoints: table `checkpoints` in the database, thread `{state.pipeline_id}` "
        f"(`python main.py show --pipeline-id {state.pipeline_id}`)",
        f"- telemetry: `{telemetry_path}`",
        "",
        "| Node | Status | Time | LLM calls | Tokens in / out |",
        "|---|---|---|---|---|",
    ]
    ends: dict[str, list] = {}
    for e in Emitter(telemetry_path).read():
        if e.status != "started":
            ends.setdefault(e.node, []).append(e)
    for node, events in ends.items():
        last = events[-1]
        ms = sum(e.duration_ms or 0 for e in events)
        calls = sum(u.calls for u in last.llm)
        tokens = f"{sum(u.input_tokens for u in last.llm):,} / " + (
            f"{sum(u.output_tokens for u in last.llm):,}"
        )
        runs = f" ({len(events)} runs)" if len(events) > 1 else ""
        lines.append(f"| {node} | {last.status}{runs} | {ms / 1000:.1f} s | "
                     f"{calls if last.llm else ''} | {tokens if last.llm else ''} |")  # fmt: skip
    return "\n".join(lines) + "\n"


def body(path: Path) -> str:
    """A written report up to the trace marker: what `reproduce` compares."""
    content = path.read_text(encoding="utf-8")
    return content.split("\n" + text.TRACE_MARKER, 1)[0].rstrip() + "\n"


def write_report(conn: sqlite3.Connection, state: PipelineState, reports_dir: Path,
                 telemetry_path: Path) -> Path:  # fmt: skip
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{state.pipeline_id}.md"
    path.write_text(render(conn, state) + trace(state, telemetry_path), encoding="utf-8")
    return path
