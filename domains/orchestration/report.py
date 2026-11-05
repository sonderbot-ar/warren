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
from domains.evaluation.hindsight import against_actuals
from domains.news.store import iso
from domains.orchestration import text
from domains.orchestration.state import PipelineState
from domains.orchestration.telemetry import Emitter
from shared_kernel.calendar import known_by

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
        "AND s.title IS NOT NULL GROUP BY a.article_id ORDER BY seen, a.article_id",
        (event_id, cutoff),
    ).fetchall()
    out, seen = [], set()
    for r in rows:  # a syndicated story repeats one headline across outlets: show it once
        key = r["title"].split(" – ")[0].split(" - ")[0].strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(f"{r['seen'][:10]} · {r['title']}")
    return out[:HEADLINES_PER_EVENT]


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
    if state.actuals_on is not None:  # pipelines written before backlog #128 have none
        lines += ["", *hindsight(conn, state)]
    if state.range_errors_sha256 is not None:  # pipelines written before backlog #167 have none
        lines += ["", *range_section(conn, state)]
    return "\n".join(lines).rstrip() + "\n"


def _miss(item) -> str:
    if item.miss is None:
        return "–"
    if item.name == "revenue":
        return f"{item.signed_miss * 100:+.1f}%"
    return f"{item.signed_miss * 100:+.2f} pts"


def hindsight(conn: sqlite3.Connection, state: PipelineState) -> list[str]:
    """Section 6 (backlog #128): the forecast against what was first reported by actuals_on."""
    h = against_actuals(conn, state.run_id, state.actuals_on)
    on = state.actuals_on.isoformat()
    lines = [f"## {text.HINDSIGHT_HEADING}", "", text.HINDSIGHT_INTRO.format(actuals_on=on), ""]
    reported = [q for q in h.quarters if q.reported]
    if not reported:
        return [*lines, text.HINDSIGHT_NONE.format(actuals_on=on)]
    unit = reported[0].items[0].unit
    lines += [
        f"| Quarter | Ends | Revenue forecast ({unit} m) | Revenue reported | Miss | "
        f"EBIT forecast ({unit} m) | EBIT reported | Miss | Filings |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    notes = []
    for q in h.quarters:
        rev, ebit = q.items
        if not q.reported:
            lines.append(f"| {q.period} | | {_m(rev.forecast)} | not yet | | {_m(ebit.forecast)} "
                         "| not yet | | |")  # fmt: skip
            continue
        filings = sorted({f"{f.form} {f.filed_at}" for i in q.items for f in i.filings})
        length = f" ({q.days} days)" if q.days and abs(q.days - 91) >= 7 else ""
        lines.append(
            f"| {q.period} | {q.period_end}{length} | {_m(rev.forecast)} | {_m(rev.actual)}"
            f"{' (derived)' if rev.derived else ''} | {_miss(rev)} | {_m(ebit.forecast)} | "
            + (f"{_m(ebit.actual)} | {_miss(ebit)}" if ebit.actual is not None else "– | –")
            + f" | {'; '.join(filings)} |"
        )
        notes += [f"- {i.missing.text}" for i in q.items if i.missing is not None]
    if any(q.items[0].derived for q in reported):
        notes.append("- derived: a fourth quarter is the year in the 10-K minus the nine months "
                     "in the 10-Qs; the company does not report it on its own")  # fmt: skip
    return [*lines, *([""] if notes else []), *notes]


def _band(values: dict | None, key: str) -> str:
    return "–" if values is None else _m(values[key])


def _range_table(r, label: str) -> list[str]:
    lines = [
        f"### {label}",
        "",
        "| Quarter | Revenue forecast | p10 | p50 | p90 | EBIT forecast | p10 | p50 | p90 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for q in r.quarters:
        b = q.bands[0]  # pooled: M9's headline band
        if b.missing is not None and b.missing.code == "beyond_horizon":
            continue
        cells = [_band(b.revenue, k) for k in ("p10", "p50", "p90")]
        ebit = [_band(b.ebit, k) for k in ("p10", "p50", "p90")]
        if b.missing is not None:
            cells, ebit = [b.missing.code, "", ""], [b.missing.code, "", ""]
        lines.append(f"| {q.period} | {_m(q.revenue_center)} | {' | '.join(cells)} | "
                     f"{_m(q.ebit_center)} | {' | '.join(ebit)} |")  # fmt: skip
    return [*lines, ""]


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def range_section(conn: sqlite3.Connection, state: PipelineState) -> list[str]:
    """Section 7 (backlog #167): the baseline's range and each simulation's shocked range, from
    the past misses filed by the as-of date, with the baseline range's track record."""
    from domains.evaluation import run_ranges as RN

    base = RN.run_ranges(conn, state.run_id, state.n_samples, check_basis=False)
    number = 7 if state.actuals_on is not None else 6
    lines = [
        f"## {number}. {text.RANGE_HEADING}",
        "",
        text.RANGE_INTRO.format(
            as_of=state.as_of.isoformat(), draws=state.n_samples, currency=base.currency
        ),  # fmt: skip
        "",
        *_range_table(base, "Baseline"),
        text.RANGE_TRACK.format(
            origins_from=RN.R.ROLLING_FROM.isoformat(),
            as_of=state.as_of.isoformat(),
            target=RN.TARGET,
        ),  # fmt: skip
        "",
    ]
    for c in base.coverage:
        if c.pool != "pooled":
            continue
        who = "all companies" if c.scope == "all" else state.ticker
        iv = f", 90% interval {_pct(c.interval[0])}–{_pct(c.interval[1])}" if c.interval else ""
        verdict = c.missing.code if c.missing else c.verdict
        lines.append(f"- {c.item}, {who}: {_pct(c.share)} inside ({c.inside} of {c.n} past "
                     f"forecasts, {c.n_quarters} quarters){iv}; {verdict}")  # fmt: skip
    lines.append("")
    by_sim: dict[str, list[str]] = {}
    for v in state.variants:
        s = state.sim.get(v)
        if s is not None:
            by_sim.setdefault(s.sim_id, []).append(v)
    notes = [n.text for n in base.notes]
    for sim_id, variants in by_sim.items():
        r = RN.run_ranges(conn, state.run_id, check_basis=False, sim_id=sim_id, coverage=False)
        label = f"With shocks: {' and '.join(variants)} (simulation {sim_id})"
        lines += _range_table(r, label)
        lines += [f"{RN.COVERAGE_IS_BASELINE.text[0].upper()}{RN.COVERAGE_IS_BASELINE.text[1:]}.",
                  ""]  # fmt: skip
        notes += [n.text for n in r.notes if n.code not in ("coverage_skipped",
                                                            "coverage_is_baseline")]  # fmt: skip
    seen = []
    for n in notes:
        if n not in seen:
            seen.append(n)
    return [*lines, *[f"- Note: {n}" for n in seen]]


def trace(state: PipelineState, telemetry_path: Path) -> str:
    lines = [
        "",
        text.TRACE_MARKER,
        "",
        f"## {6 + (state.actuals_on is not None) + (state.range_errors_sha256 is not None)}. Trace",
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
