"""Shock proposal (M6 Step B, LLM 2): one proposal set per case and variant.

The model reads all of a case's classified events at once and picks, per driver, at most one
shock as classes (direction, size, duration, start quarter). Code sizes each with `scales`, from
the company's own history as first reported on the case date, and checks it with M4's validator.
The model's schema has no field for a number, and an answer with an extra field is invalid.
"""

import hashlib
import json
import sqlite3
import warnings
from dataclasses import dataclass
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from domains.analysis import dcf
from domains.analysis.runs import load_assumptions
from domains.evaluation.harness import ITEMS, _alternative, first_reported
from domains.fundamentals.facts import get_facts
from domains.llm import calls, scales
from domains.llm.client import LLMClient
from domains.llm.extract import PROMPT as EXTRACT_PROMPT
from domains.llm.extract import Company, Variant, choose_events, mask, mask_pattern, window_start
from domains.llm.taxonomy import NOT_ABOUT
from domains.news.gdelt import CASE_TZ, known_by
from domains.news.matching import AliasSet
from domains.news.store import iso

NODE = "propose_shocks"
PROMPT = "propose_shocks"
DRIVERS = ("revenue_growth", "operating_margin", "capex_intensity", "risk_premium")
HISTORY_QUARTERS = 20  # 12 four-quarter changes of revenue growth need 20 quarters of revenue
SHOWN_QUARTERS = 8


class ProposedShock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    driver: Literal["revenue_growth", "operating_margin", "capex_intensity", "risk_premium"]
    direction: Literal["up", "down"]
    size: Literal["small", "medium", "large"]
    duration: Literal["one_quarter", "fading", "lasting", "permanent"]
    start_quarter: int = Field(..., ge=1, le=4)
    rationale: str = Field(..., min_length=1, max_length=600)
    evidence: list[str] = Field(..., min_length=1)


class ShockProposalSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposals: list[ProposedShock] = Field(..., max_length=4)
    no_material_impact: bool
    reason: str = Field(..., min_length=1, max_length=600)


@dataclass(frozen=True)
class CaseEvent:
    id: str  # e1, e2, … in the prompt
    classification_id: int
    event_id: str
    event_type: str
    materiality: str
    summary: str
    headlines: list[str]  # titles of the headlines about the company


def checker(events: list[CaseEvent]):
    ids = {e.id: e for e in events}

    def check(value: ShockProposalSet) -> None:
        drivers = [p.driver for p in value.proposals]
        if len(set(drivers)) != len(drivers):
            raise ValueError("at most one shock per driver")
        if not value.proposals and not value.no_material_impact:
            raise ValueError("no proposals: set no_material_impact to true")
        if value.proposals and value.no_material_impact:
            raise ValueError("no_material_impact is true but shocks are proposed")
        for p in value.proposals:
            unknown = [e for e in p.evidence if e not in ids]
            if unknown:
                raise ValueError(f"evidence cites unknown events: {', '.join(unknown)}")
            if (
                p.driver == "risk_premium"
                and p.duration == "permanent"
                and not any(ids[e].materiality == "high" for e in p.evidence)
            ):
                raise ValueError("a permanent risk premium needs a cited high-materiality event")

    return check


# -- history, point-in-time -------------------------------------------------------------------


@dataclass(frozen=True)
class History:
    """Quarterly ratios as first reported on the as-of date, oldest first (fractions)."""

    revenue_growth: list[float]
    operating_margin: list[float]
    capex_intensity: list[float]
    last_quarter: tuple[int, int] | None  # (fiscal year, quarter) of the latest ratio


def _contiguous_tail(keys: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out = []
    for key in sorted(keys, reverse=True):
        if out:
            year, q = out[-1]
            if key != ((year, q - 1) if q > 1 else (year - 1, 4)):
                break
        out.append(key)
    return out[::-1]


def driver_history(conn: sqlite3.Connection, cik: str, as_of: date, run_id: str) -> History:
    """The three ratios over the last quarters reported by `as_of`, as first reported.

    EBIT uses the run's own definition (its `history:ebit` alternative), as the harness does; a
    quarter reported only under another definition ends the series there.
    """
    rows = load_assumptions(conn, run_id)
    ebit_rows = sorted((a for a in rows if a.name == "history:ebit"), key=lambda a: a.period)
    alternative = _alternative(ebit_rows[-1].method) if ebit_rows else 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        facts = get_facts(conn, cik, [*ITEMS, "capex"], as_of, mode="first_reported",
                          frequency="quarterly")  # fmt: skip
    by_key = {(f.canonical_name, f.fiscal_year, f.fiscal_period): f for f in facts}
    quarters = _contiguous_tail([(f.fiscal_year, int(f.fiscal_period[1]))
                                 for f in facts if f.canonical_name == "revenue"])  # fmt: skip
    quarters = quarters[-HISTORY_QUARTERS:]
    revenue, margin, capex = [], [], []
    last = None
    for year, q in quarters:
        try:
            actual = first_reported(by_key, year, q, alternative)
        except ValueError:
            actual = None
        cap = by_key.get(("capex", year, f"Q{q}"))
        if actual is None or cap is None or actual.revenue.value <= 0:
            revenue, margin, capex = [], [], []  # a gap: keep only what follows it
            continue
        revenue.append(actual.revenue.value)
        margin.append(actual.ebit / actual.revenue.value)
        capex.append(cap.value / actual.revenue.value)
        last = (year, q)
    growth = [b / a - 1 for a, b in zip(revenue, revenue[4:], strict=False)]
    return History(growth, margin, capex, last)


def series_for(history: History, driver: str) -> list[float]:
    return getattr(history, driver) if driver != "risk_premium" else []


# -- the call ----------------------------------------------------------------------------------


def current_keys() -> tuple[str, str, str, str]:
    """(proposal model, proposal prompt hash, extraction model, extraction prompt hash) now."""
    return (calls.node_model(NODE).model, calls.latest_prompt(PROMPT).sha256,
            calls.node_model("extract_events").model,
            calls.latest_prompt(EXTRACT_PROMPT).sha256)  # fmt: skip


def case_events(conn: sqlite3.Connection, case_id: str, variant: str, model: str,
                extract_sha256: str) -> list[dict]:  # fmt: skip
    """The case's `ok` classifications in this variant by this model and extraction prompt, of the
    events extraction chooses for the case window now (`extract.choose_events`), minus
    not-about-company events: one row per event, never one per stored prompt version, and never
    an event from outside the window that an earlier choice classified."""
    rows = conn.execute(
        "SELECT c.*, e.event_run_id, e.source_count, e.first_seen, e.last_seen, r.as_of, r.tz "
        "FROM event_classifications c JOIN events e USING (event_id) "
        "JOIN event_runs r ON r.event_run_id = e.event_run_id "
        "JOIN case_llm_status s ON s.event_run_id = e.event_run_id AND s.variant = c.variant "
        "WHERE s.case_id = ? AND c.variant = ? AND c.model = ? AND c.prompt_sha256 = ? "
        "AND c.status = 'ok' ORDER BY e.first_seen, c.event_id",
        (case_id, variant, model, extract_sha256),
    ).fetchall()
    if not rows:
        return []
    start = window_start(date.fromisoformat(rows[0]["as_of"]), ZoneInfo(rows[0]["tz"]))
    chosen = {e["event_id"] for e in choose_events([dict(r) for r in rows], start)}
    return [r for r in rows if r["event_id"] in chosen and r["event_type"] != NOT_ABOUT]


def inputs_sha256(extract_sha256: str, rows: list) -> str:
    """What a proposal set reads: the extraction prompt and the classifications, by id."""
    ids = ",".join(str(i) for i in sorted(r["classification_id"] for r in rows))
    return hashlib.sha256(f"{extract_sha256}|{ids}".encode()).hexdigest()


def current_set(conn: sqlite3.Connection, case_id: str, variant: str) -> sqlite3.Row | None:
    """The stored set the current models, prompts and event choice give for a case, if any."""
    p_model, p_sha, x_model, x_sha = current_keys()
    rows = case_events(conn, case_id, variant, x_model, x_sha)
    if not rows:
        return None
    return conn.execute(
        "SELECT * FROM proposal_sets WHERE case_id = ? AND event_run_id = ? AND variant = ? AND "
        "model = ? AND prompt_sha256 = ? AND inputs_sha256 = ?",
        (case_id, rows[0]["event_run_id"], variant, p_model, p_sha, inputs_sha256(x_sha, rows)),
    ).fetchone()  # fmt: skip


def _titles(conn: sqlite3.Connection, about_json: str, as_of: date) -> list[str]:
    ids = [a for a, about in json.loads(about_json).items() if about]
    titles = []
    for article_id in ids:
        row = conn.execute(
            "SELECT title FROM article_sightings WHERE article_id = ? AND seen_at < ? "
            "ORDER BY seen_at LIMIT 1",
            (article_id, iso(known_by(as_of, CASE_TZ))),
        ).fetchone()
        if row and row["title"]:
            titles.append(row["title"])
    return titles


def render(events: list[CaseEvent], inp: dcf.Inputs, history: History) -> tuple[str, str]:
    lines = []
    for e in events:
        lines.append(f"{e.id} | {e.event_type} | materiality {e.materiality} | {e.summary}")
        lines += [f"    - {t}" for t in e.headlines]

    def pct(values):
        return ", ".join(f"{100 * v:.1f}%" for v in values)

    forecast = "\n".join(
        f"{name}: {pct(inp.driver[row][: dcf.QUARTERS])}"
        for name, row in (("revenue growth (vs the same quarter a year earlier)", "revenue_growth"),
                          ("operating margin", "operating_margin"),
                          ("capex intensity (capex / revenue)", "capex_pct"))
    )  # fmt: skip
    past = "\n".join(
        f"{name}: {pct(values[-SHOWN_QUARTERS:])}"
        for name, values in (("revenue growth", history.revenue_growth),
                             ("operating margin", history.operating_margin),
                             ("capex intensity", history.capex_intensity))
    )  # fmt: skip
    return "\n".join(lines), f"Forecast, Q1 to Q8:\n{forecast}\n\nReported, Q−8 to Q−1:\n{past}"


def propose_case(
    conn: sqlite3.Connection,
    client: LLMClient,
    case_id: str,
    co: Company,
    as_of: date,
    run_id: str,
    aliases: AliasSet,
    variant: Variant,
    batch_id: str = "propose",
    budget: int = calls.DEFAULT_BUDGET,
    scale_table: dict | None = None,
) -> int | None:
    """Propose and size the case's shocks in one variant; the proposal set id, or None when the
    case has no events to propose from. A stored `ok` set is reused; a failed one is retried."""
    prompt = calls.latest_prompt(PROMPT)
    model = calls.node_model(NODE).model
    extract_model = calls.node_model("extract_events").model
    table = scale_table or scales.load_scales()
    extract_sha = calls.latest_prompt(EXTRACT_PROMPT).sha256
    rows = case_events(conn, case_id, variant, extract_model, extract_sha)
    if not rows:
        return None
    event_run_id = rows[0]["event_run_id"]
    key = (case_id, event_run_id, variant, model, prompt.sha256, inputs_sha256(extract_sha, rows))
    stored = conn.execute(
        "SELECT set_id, status FROM proposal_sets WHERE case_id = ? AND event_run_id = ? AND "
        "variant = ? AND model = ? AND prompt_sha256 = ? AND inputs_sha256 = ?", key,
    ).fetchone()  # fmt: skip
    if stored is not None and stored["status"] == "ok":
        return stored["set_id"]
    if stored is not None:
        conn.execute("DELETE FROM proposal_sets WHERE set_id = ?", (stored["set_id"],))
    pattern = mask_pattern(aliases, co)
    events = []
    for n, r in enumerate(rows, start=1):
        titles = _titles(conn, r["about_json"], as_of)
        if variant == "masked":
            titles = [mask(t, pattern) for t in titles]
        events.append(CaseEvent(f"e{n}", r["classification_id"], r["event_id"], r["event_type"],
                                r["materiality"], r["summary"], titles))  # fmt: skip
    inp = dcf.inputs(load_assumptions(conn, run_id))
    history = driver_history(conn, co.cik, as_of, run_id)
    events_text, numbers = render(events, inp, history)
    slots = {
        "company": f"{co.name} ({co.ticker})" if variant == "named" else "the Company",
        "as_of": as_of.isoformat() if variant == "named" else "day 0",
        "events": events_text,
        "numbers": numbers,
    }
    try:
        result = calls.structured_call(conn, client, NODE, prompt, slots, ShockProposalSet,
                                       f"{case_id}:{variant}", batch_id, budget,
                                       checker(events))  # fmt: skip
    except calls.LLMRejected:
        cur = conn.execute(
            "INSERT INTO proposal_sets (case_id, event_run_id, variant, model, prompt_sha256, "
            "inputs_sha256, run_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'failed')",
            (*key, run_id),
        )  # fmt: skip
        conn.commit()
        return cur.lastrowid
    value: ShockProposalSet = result.value
    by_id = {e.id: e for e in events}
    with conn:
        set_id = conn.execute(
            "INSERT INTO proposal_sets (case_id, event_run_id, variant, model, prompt_sha256, "
            "inputs_sha256, call_id, run_id, status, no_impact, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?)",
            (*key, result.call_id, run_id, int(value.no_material_impact), value.reason),
        ).lastrowid
        for p in value.proposals:
            s = scales.sigma(p.driver, series_for(history, p.driver), table)
            bounds = scales.Bounds(
                margin=scales.margin_bounds(history.operating_margin, s, table)
                if p.driver == "operating_margin" and history.operating_margin else None,
                level_band=table["revenue_level_band"] / 100,
            )  # fmt: skip
            sized = scales.size_shock(p.driver, p.direction, p.size, p.duration, p.start_quarter,
                                      s, inp, bounds, table)  # fmt: skip
            evidence = [by_id[e].event_id for e in p.evidence]
            conn.execute(
                "INSERT INTO shock_proposals (set_id, driver, direction, size, duration, "
                "start_quarter, rationale, evidence_json, sigma, sigma_flag, low, base, high, "
                "horizon, decay, clipped, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed')",
                (set_id, p.driver, p.direction, p.size, p.duration, p.start_quarter, p.rationale,
                 json.dumps(evidence), s.value, s.flag, sized.low, sized.base, sized.high,
                 sized.horizon, sized.decay, int(sized.clipped)),
            )  # fmt: skip
    return set_id
