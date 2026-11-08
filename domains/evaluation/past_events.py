"""Past events, chosen by rule (backlog #146, front-end R5, brief questions 10–15).

For a company and an event type, as of a date D: the case library's events of that type before
D, of any company, each with what the baseline forecast just before it, what was first reported
after it, quarter by quarter, and that miss beside Warren's usual miss for the company at the
same horizon on quarters without an event (M9's monthly forecasts, known by D). Plus n, a
thin-evidence flag, the scope-change warning and a sourced table of metrics to watch. No AI
anywhere: the cases come from a rule over a checked-in file, the numbers from stored runs and
filings. Nothing is written; gaps are coded, never raised. Design:
docs/designs/backlog-146-past-events.md.
"""

import csv
import hashlib
import re
import sqlite3
import statistics
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from domains.analysis.financial_math import ratio
from domains.analysis.reported import Coded, Filing
from domains.evaluation import run_ranges as RN
from domains.evaluation.cases import CASES_PATH, EVENT_TYPES, Case, cases_sha256, load_cases
from domains.evaluation.harness import EvaluationError, score
from domains.evaluation.hindsight import Hindsight, against_actuals
from domains.evaluation.track_record import ITEMS, MIN_QUARTERS, _group_rows
from domains.fundamentals.universe import coverage_gap, get_universe_company
from shared_kernel.calendar import last_ended_day

METRICS_PATH = Path(__file__).parent / "event_metrics.csv"
METRIC_COLUMNS = ("event_type", "metric_id", "metric", "where_to_find", "source", "source_url")
# event types a question may name that have metrics to watch but no case in the library yet,
# so the answer is n = 0 and the metrics (brief Q13: an election or a change of policy)
UNCASED_TYPES = frozenset({"policy"})
ASKABLE = frozenset(EVENT_TYPES - {"control"}) | UNCASED_TYPES
# below this many cases with a reported quarter the evidence is thin: even if every case missed
# by more than the company's usual median, an exact two-sided sign test (backtest.sign_test)
# could not reach p < 0.05 (5 of 5 gives 0.0625; 6 of 6 gives 0.031). A working rule.
THIN_BELOW = 6
USUAL_P = 0.9  # `beyond_usual`: the miss is above the usual misses' 90th percentile
_SCOPE = re.compile(r"\(h([1-4])(?:-h([1-4]))?\)")
_SCOPE_FROM = re.compile(r"from (\d{4}-\d{2}-\d{2})")


class PastEventsError(EvaluationError):
    """A request the call refuses, with a code the app can translate."""

    def __init__(self, code: str, params: dict, text: str):
        super().__init__(text)
        self.code, self.params, self.text = code, params, text

    def coded(self) -> Coded:
        return Coded(self.code, self.params, self.text)


@dataclass(frozen=True)
class Metric:
    metric_id: str
    metric: str
    where_to_find: str
    source: str
    source_url: str | None


@dataclass(frozen=True)
class Usual:
    n_quarters: int  # the company's target quarters at this horizon without an event
    median_miss: float | None
    p90_miss: float | None
    rank: float | None  # share of the usual misses smaller than this miss
    beyond_usual: bool | None  # above p90_miss; None with fewer than MIN_QUARTERS
    missing: Coded | None = None


@dataclass(frozen=True)
class EventItem:
    forecast: float
    actual: float | None
    miss: float | None
    signed_miss: float | None  # positive: Warren forecast too high
    miss_unit: str
    filings: list[Filing]
    missing: Coded | None
    usual: Usual | None


@dataclass(frozen=True)
class EventQuarter:
    period: str
    period_end: date | None
    horizon: int
    scope_change: bool
    ended_before_event: bool  # the quarter ended before the event: shown, not compared
    forecast_margin: float | None
    actual_margin: float | None
    items: dict[str, EventItem]


@dataclass(frozen=True)
class PastCase:
    case_id: str
    ticker: str
    event_date: date
    event_type: str
    description: str
    source_url: str
    scope_change: str | None
    same_company: bool
    same_type: bool
    same_mechanism: bool | None  # None until #147 tags a mechanism; the type mixes them
    direction: str | None  # same or opposite: not recorded until #147
    run_id: str | None
    run_as_of: date | None
    reported_quarters: int
    compared_quarters: int  # reported, not scope-changed, with a usual miss to compare
    quarters: list[EventQuarter]
    missing: Coded | None = None
    history_cut: Coded | None = None  # its company's filings stop by D (backlog #269)


@dataclass(frozen=True)
class PastEvents:
    ticker: str
    event_type: str
    as_of: date
    as_of_default: bool
    rule: str
    cases_sha256: str
    metrics_sha256: str
    n: int  # cases with at least one quarter reported by as_of
    n_compared: int  # cases with at least one quarter compared with the usual miss
    n_listed: int
    thin_evidence: bool
    threshold: int
    cases: list[PastCase]
    same_company_other_type: list[PastCase]
    metrics: list[Metric]
    notes: list[Coded]
    missing: Coded | None = None

    def to_dict(self) -> dict:
        return RN._plain(asdict(self))


# -- metrics to watch --------------------------------------------------------------------------


def metrics_sha256(path: Path = METRICS_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_metrics(path: Path = METRICS_PATH) -> dict[str, list[Metric]]:
    """The metrics-to-watch table by event type, validated: every askable type has a row, every
    row a source, no unknown type, unique ids within a type."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != METRIC_COLUMNS:
            raise ValueError(f"metrics file columns must be {METRIC_COLUMNS}, got "
                             f"{reader.fieldnames}")  # fmt: skip
        rows = list(enumerate(reader, start=2))
    out: dict[str, list[Metric]] = {}
    for line, row in rows:
        kind = (row["event_type"] or "").strip()
        if kind not in ASKABLE:
            raise ValueError(f"metrics line {line}: unknown event type {kind!r}")
        for name in ("metric_id", "metric", "where_to_find", "source"):
            if not (row[name] or "").strip():
                raise ValueError(f"metrics line {line}: {name} is empty")
        metric_id = row["metric_id"].strip()
        if any(m.metric_id == metric_id for m in out.get(kind, [])):
            raise ValueError(f"metrics line {line}: duplicate {kind}/{metric_id}")
        out.setdefault(kind, []).append(Metric(
            metric_id, row["metric"].strip(), row["where_to_find"].strip(),
            row["source"].strip(), (row["source_url"] or "").strip() or None,
        ))  # fmt: skip
    if lacking := sorted(ASKABLE - set(out)):
        raise ValueError(f"metrics file has no row for {', '.join(lacking)}")
    return out


# -- the rule ----------------------------------------------------------------------------------


def rule_text(event_type: str) -> str:
    return (f"every case in the library of type {event_type}, of any company, dated before the "
            "question's date; controls are never included")  # fmt: skip


def select_cases(
    cases: list[Case], ticker: str, event_type: str, on: date
) -> tuple[list[Case], list[Case]]:
    """(the cases the rule takes, the company's own cases of other types), both before `on`,
    the company's first, then newest first."""

    def order(c: Case) -> tuple:
        return (c.ticker != ticker, -c.event_date.toordinal(), c.case_id)

    before = [c for c in cases if not c.is_control and c.event_date < on]
    matches = [c for c in before if c.event_type == event_type]
    others = [c for c in before if c.ticker == ticker and c.event_type != event_type]
    return sorted(matches, key=order), sorted(others, key=order)


def scope_from(text: str | None) -> date | None:
    """The date a case's `scope_change` text says the deal was consolidated from."""
    found = _SCOPE_FROM.search(text or "")
    return date.fromisoformat(found.group(1)) if found else None


def in_scope(text: str | None, horizon: int, period_end: date | None) -> bool:
    """Whether a forecast quarter holds the acquired business: its period ends on or after the
    consolidation date. The file's "(hN)" labels are a fallback only, for text without a date
    or a quarter not yet reported; three of them are off by a quarter (the analyst's check at
    the design review), so the date decides."""
    start = scope_from(text)
    if start is not None and period_end is not None:
        return period_end >= start
    return horizon in scope_horizons(text)


def scope_horizons(text: str | None) -> set[int]:
    """The horizons a case's `scope_change` text names: "(h4)", "(h3-h4)", "(h1-h4)"."""
    out: set[int] = set()
    for first, last in _SCOPE.findall(text or ""):
        out.update(range(int(first), int(last or first) + 1))
    return out


# -- the usual miss ----------------------------------------------------------------------------


def case_runs(conn: sqlite3.Connection, case_ids: list[str]) -> dict[str, str]:
    """Each case's baseline run, from the newest backtest batch that scored it."""
    out: dict[str, str] = {}
    for cid in case_ids:
        row = conn.execute(
            "SELECT r.run_id FROM eval_results r JOIN eval_batches b USING (batch_id) "
            "WHERE r.case_id = ? AND r.variant = 'baseline' "
            "ORDER BY b.created_at DESC, b.batch_id DESC LIMIT 1", (cid,)).fetchone()  # fmt: skip
        if row is not None:
            out[cid] = row["run_id"]
    return out


def event_periods(conn: sqlite3.Connection, cases: list[Case]) -> set[str]:
    """The target periods an event case forecast at horizons 1 to its horizon, and the periods a
    control's `scope_change` names (an acquisition consolidated: not an ordinary quarter either),
    from their stored baseline rows."""
    out: set[str] = set()
    for c in cases:
        rows = conn.execute(
            "SELECT DISTINCT period, horizon, period_end FROM eval_results WHERE case_id = ? "
            "AND variant = 'baseline' AND horizon <= ?", (c.case_id, c.horizon_quarters),
        ).fetchall()  # fmt: skip
        for period, h, end in rows:
            ended = date.fromisoformat(end) if end else None
            if not c.is_control or in_scope(c.scope_change, h, ended):
                out.add(period)
    return out


def usual_misses(
    conn: sqlite3.Connection,
    ticker: str,
    on: date,
    excluded: set[str],
    flags: set[tuple[str, str, str]] | None,
) -> dict[tuple[str, int], list[float]]:
    """(item, horizon) -> the company's absolute misses on target quarters without an event, one
    per (target quarter, horizon) from the first monthly forecast that made it (#145's rows),
    actuals filed by `on`; periods in `excluded` and basis-flagged quarters are left out."""
    out: dict[tuple[str, int], list[float]] = {}
    for (period, h), group in _group_rows(conn, ticker, on).items():
        if period in excluded:
            continue
        if flags and any((g["origin_id"], period, i) in flags for g in group for i in ITEMS):
            continue
        first = group[0]
        for item, fc, act in (("revenue", first["rf"], first["ra"]),
                              ("ebit", first["ef"], first["ea"])):  # fmt: skip
            out.setdefault((item, h), []).append(score(item, fc, act, first["ra"])[0])
    return {k: sorted(v) for k, v in out.items()}


def compare(miss: float, usual: list[float]) -> Usual:
    """This miss against the company's usual misses at the same horizon."""
    n = len(usual)
    if n == 0:
        return Usual(0, None, None, None, None, _few(0))
    p90 = statistics.quantiles(usual, n=10, method="inclusive")[8] if n >= 2 else usual[0]
    rank = sum(u < miss for u in usual) / n
    few = n < MIN_QUARTERS
    return Usual(n, statistics.median(usual), p90, rank, None if few else miss > p90,
                 _few(n) if few else None)  # fmt: skip


# -- codes -------------------------------------------------------------------------------------


def _few(n: int) -> Coded:
    return Coded(
        "few_usual_quarters", {"n_quarters": n, "min_quarters": MIN_QUARTERS},
        f"only {n} quarters without an event at this horizon, fewer than {MIN_QUARTERS}: no "
        "verdict on whether this miss was unusual",
    )  # fmt: skip


SCOPE_QUARTER = Coded(
    "scope_change", {},
    "an acquisition changed the company's scope in this quarter: most of the gap is the bought "
    "company being added, not a forecast miss, so it is not compared with the usual miss",
)  # fmt: skip


def _ended_before(period: str, event: date) -> Coded:
    return Coded(
        "ended_before_event", {"period": period, "event_date": event.isoformat()},
        f"{period} ended before the event on {event}, though it was not yet reported: its miss "
        "is shown but not read as the event's effect",
    )  # fmt: skip


def _quarters_missing_clause(periods: list[str]) -> str:
    one = len(periods) == 1
    return (f"its own {'quarter' if one else 'quarters'} {', '.join(periods)} "
            f"{'is' if one else 'are'} not in the data either")  # fmt: skip


def _thin(n: int, reason: str, cut: list[dict] | None = None) -> Coded:
    """`cut`: the counted cases (a quarter reported by D) whose company's filings are missing by
    D, each `{case_id, ticker, role, history_ends, effect, quarters_missing}` with `role` the
    company's `beyond_history` note's (backlog #262) and `effect` what the cut takes from the
    case (backlog #269, see `history_cut`). They stay in `n`: the event happened and some of its
    quarters are filed; what stops early is the company's typical forecast errors, and with
    `own_quarters_missing` some of the case's own quarters too."""
    cut = sorted(cut or [], key=lambda c: c["case_id"])
    if reason == "few_cases":
        text = (f"only {n} past cases: even if every one had missed by more than usual, that "
                f"could be chance. From {THIN_BELOW} cases a test becomes possible, which is "
                "still not proof")  # fmt: skip
    else:
        text = (
            f"{n} past cases, but the library does not record which way each one went (a "
            "cut or a raise, a rise or a fall), so they cannot be read together as evidence"
        )
    if cut:
        parts = []
        for c in cut:
            own = ", the question's company" if c["role"] == "question" else ""
            lost = c.get("quarters_missing") or []
            gone = f"; {_quarters_missing_clause(lost)}" if lost else ""
            parts.append(f"{c['case_id']} ({c['ticker']}{own}, from {c['history_ends']} on{gone})")
        one = len(cut) == 1
        whose, their = ("its company's", "Its") if one else ("their companies'", "Their")
        text += (f". Counted, though {whose} filings are missing in Warren's data from a date "
                 f"before this question: {'; '.join(parts)}. {their} typical forecast errors stop "
                 "at that date (see the coverage note)")  # fmt: skip
    params = {"n": n, "threshold": THIN_BELOW, "reason": reason, "cut_cases": len(cut),
              "cut_case_ids": [c["case_id"] for c in cut], "cut": cut}  # fmt: skip
    return Coded("thin_evidence", params, text)


def _notes(event_type: str, on: date) -> list[Coded]:
    return [
        Coded("rule", {"event_type": event_type, "as_of": on.isoformat()},
              rule_text(event_type)),
        Coded("baseline_only", {},
              "the forecasts are the baseline's, made the day before each event, without news "
              "shocks"),
        Coded("usual_from_monthly_forecasts", {"as_of": on.isoformat()},
              "the usual miss is the company's own, from Warren's monthly forecasts at the same "
              "horizon, on quarters without an event, as known on the question's date; it "
              "includes 2020's pandemic quarters unless an event case covered them"),
        Coded("beyond_usual_by_chance", {"share": round(1 - USUAL_P, 2)},
              "about 1 in 10 ordinary quarters also misses by more than the usual line, so one "
              "unusual quarter alone does not show the event caused it"),
        Coded("past_outcomes_not_forecast", {},
              "these are what happened after past events, not a forecast of the next one"),
        Coded("mechanism_untagged", {"event_type": event_type},
              "cases are matched by event type only: one type can hold different mechanisms "
              "(a guidance cut for inflation, for currency or for supply), so a same-type case "
              "is not necessarily the same mechanism"),
        Coded("direction_not_recorded", {},
              "the library does not yet record whether a case moved in the same direction as "
              "the question's event"),
    ]  # fmt: skip


MERGER_SHOCKS = Coded(
    "merger_shocks_missized", {"event_type": "m_and_a", "backtest_cases": 2},
    "In its two merger cases, Warren's backtest found that its AI news shocks mis-size mergers: a "
    "shock's size comes from how much the company's revenue usually moves, not from the size of "
    "the company bought. These forecasts are the baseline's, without news shocks, so that error "
    "is not here. They have a different one: they leave out the bought company's revenue, so "
    "after a deal closes part of the gap is the added revenue, not a surprise (Warren marks those "
    "quarters as a scope change and does not compare them with the usual miss)",
)  # fmt: skip


def coverage_notes(question: str, cases: set[str], on: date) -> list[Coded]:
    """`beyond_history`, as on a run (v0.9.22), for each company in the answer whose pinned CIK's
    filings are missing from its `history_ends` on, when that is on or before `on` (Exxon from
    2026-08-03): its recent quarters and usual misses end early (backlog #252). The CIK is the
    one `universe.csv` pins, so a successor ingested under the same ticker can't hide the note.
    `role` says whether the company is the question's or only a past case's (backlog #256): the
    question's company first, then the case companies by ticker."""
    out = []
    for t in [question, *sorted(cases - {question})]:
        gap = coverage_gap(get_universe_company(t).cik, on)
        if gap is None:
            continue
        text, params = gap
        role = "question" if t == question else "case"
        if role == "case":  # said first, so the rest is not read as about the question
            text = (
                f"{t} is in this answer as a past case, not the question's company: its filings "
                f"from {params['history_ends']} on are missing here, so its typical forecast "
                "errors, and any of its case quarters reported from then on, stop at that date. "
                f"{text}"
            )
        out.append(Coded("beyond_history", {**params, "role": role}, text))
    return out


def history_cut(c: PastCase, stopped: dict) -> Coded:
    """What a company's filings cut (its `beyond_history` note's params, `stopped`) takes from
    one of its cases, as of D (backlog #269). Its typical forecast errors always stop at
    `history_ends`. `effect`: `no_stored_run` when the case has no stored baseline run (nothing
    of its own is in the data, cut or not); `usual_only` when every quarter of its horizon is
    reported by D; `own_quarters_missing` when some are not, named in `quarters_missing` (each a
    `quarters[].period` of the case). "Reported" is the revenue line, as `reported_quarters`
    counts it. Every filing before `history_ends` is in the data, so an unreported quarter was
    filed from then on, or not yet by D; Warren can't tell which, and the text says the quarter
    is missing, not that the cut removed it."""
    ends = stopped["history_ends"]
    lost = [q.period for q in c.quarters if q.items["revenue"].actual is None]
    text = (f"{c.ticker}'s filings from {ends} on are missing in Warren's data, so its typical "
            "forecast errors stop at that date")  # fmt: skip
    if c.missing is not None:
        effect = "no_stored_run"
        text += "; this case has no stored forecast, so none of its own quarters are compared"
    elif lost:
        effect = "own_quarters_missing"
        one = len(lost) == 1
        text += (f"; this case's {'quarter' if one else 'quarters'} {', '.join(lost)} "
                 f"{'is' if one else 'are'} not in the data by the question's date either (not "
                 "yet filed, or filed after that date), so they can't be compared while its "
                 "filings stop there")  # fmt: skip
    else:
        effect = "usual_only"
        text += ("; every quarter of this case is in the data, only the yardstick it is "
                 "compared with is shorter")  # fmt: skip
    params = {"ticker": c.ticker, "role": stopped["role"], "history_ends": ends,
              "effect": effect, "quarters_missing": lost}  # fmt: skip
    return Coded("history_cut", params, text)


# -- one case ----------------------------------------------------------------------------------


def _margin(ebit: float | None, revenue: float | None) -> float | None:
    if ebit is None or revenue is None or revenue <= 0:
        return None
    return ratio(ebit, revenue)


def build_case(
    case: Case,
    ticker: str,
    event_type: str,
    run_id: str | None,
    seen: Hindsight | None,
    usual: dict[tuple[str, int], list[float]],
    on: date | None = None,
) -> PastCase:
    # a deal consolidated after the question's date was not public yet: no scope text, no flag
    closed = scope_from(case.scope_change)
    scope = "" if on is not None and closed is not None and closed > on else case.scope_change
    common = dict(
        case_id=case.case_id, ticker=case.ticker, event_date=case.event_date,
        event_type=case.event_type, description=case.description, source_url=case.source_url,
        scope_change=scope or None, same_company=case.ticker == ticker,
        same_type=case.event_type == event_type, same_mechanism=None, direction=None,
        run_id=run_id,
    )  # fmt: skip
    if run_id is None or seen is None:
        missing = Coded("not_scored", {"case_id": case.case_id},
                        f"{case.case_id} has no stored baseline run")  # fmt: skip
        return PastCase(**common, run_as_of=None, reported_quarters=0, compared_quarters=0,
                        quarters=[], missing=missing)  # fmt: skip
    quarters, reported, compared = [], 0, 0
    for q in seen.quarters[: case.horizon_quarters]:
        by = {i.name: i for i in q.items}
        scoped = bool(scope) and in_scope(scope, q.horizon, q.period_end)
        before = q.period_end is not None and q.period_end < case.event_date
        items = {}
        for name in ITEMS:
            it = by[name]
            u = None
            if before and it.miss is not None:
                u = Usual(0, None, None, None, None, _ended_before(q.period, case.event_date))
            elif scoped and it.miss is not None:
                u = Usual(0, None, None, None, None, SCOPE_QUARTER)
            elif it.miss is not None:
                u = compare(it.miss, usual.get((name, q.horizon), []))
            items[name] = EventItem(it.forecast, it.actual, it.miss, it.signed_miss, it.miss_unit,
                                    it.filings, it.missing, u)  # fmt: skip
        rev, ebit = by["revenue"], by["ebit"]
        reported += q.reported
        compared += any(x.usual is not None and x.usual.n_quarters > 0 for x in items.values())
        quarters.append(EventQuarter(
            q.period, q.period_end, q.horizon, scoped, before, _margin(ebit.forecast, rev.forecast),
            _margin(ebit.actual, rev.actual), items,
        ))  # fmt: skip
    return PastCase(**common, run_as_of=seen.as_of, reported_quarters=reported,
                    compared_quarters=compared, quarters=quarters)  # fmt: skip


# -- the call ----------------------------------------------------------------------------------


def past_events(
    conn: sqlite3.Connection,
    ticker: str,
    event_type: str,
    as_of: date | None = None,
    now: datetime | None = None,
    cases: list[Case] | None = None,
    check_basis: bool = True,
    hindsight: Callable[[sqlite3.Connection, str, date], Hindsight] = against_actuals,
) -> PastEvents:
    """Past cases of `event_type` for a question about `ticker`, as of `as_of` (default: the last
    day ended in New York)."""
    ticker = ticker.upper()
    if conn.execute("SELECT 1 FROM companies WHERE ticker = ?", (ticker,)).fetchone() is None:
        raise EvaluationError(f"{ticker} has not been ingested")
    if event_type not in ASKABLE:
        raise PastEventsError(
            "unknown_event_type", {"event_type": event_type, "allowed": sorted(ASKABLE)},
            f"{event_type!r} is not an event type of the case library: one of "
            f"{', '.join(sorted(ASKABLE))}",
        )  # fmt: skip
    default = as_of is None
    if default:
        as_of = last_ended_day(now or datetime.now(UTC))
    library = cases if cases is not None else load_cases(CASES_PATH)
    chosen, others = select_cases(library, ticker, event_type, as_of)
    runs = case_runs(conn, [c.case_id for c in chosen + others])

    usual_by: dict[str, dict] = {}
    for company in sorted({c.ticker for c in chosen + others}):
        # the company's cases public by D: an event after D was not known yet
        events = [c for c in library if c.ticker == company and c.event_date < as_of
                  and (not c.is_control or c.scope_change)]  # fmt: skip
        flags = RN.basis_flags(conn, company, as_of) if check_basis else None
        usual_by[company] = usual_misses(conn, company, as_of, event_periods(conn, events), flags)

    def build(c: Case) -> PastCase:
        rid = runs.get(c.case_id)
        seen = hindsight(conn, rid, as_of) if rid else None
        return build_case(c, ticker, event_type, rid, seen, usual_by[c.ticker], as_of)

    coverage = coverage_notes(ticker, {c.ticker for c in chosen + others}, as_of)
    stopped = {note.params["ticker"]: note.params for note in coverage}

    def flagged(c: PastCase) -> PastCase:
        if c.ticker not in stopped:
            return c
        return replace(c, history_cut=history_cut(c, stopped[c.ticker]))

    built = [flagged(build(c)) for c in chosen]
    n = sum(c.reported_quarters > 0 for c in built)
    n_compared = sum(c.compared_quarters > 0 for c in built)
    notes = _notes(event_type, as_of)
    # until #147 records each case's direction, cases of one type may point opposite ways (P&G
    # and Coca-Cola raised their guidance; the other four cut it), so no count is enough
    thin = True
    cut = [
        {"case_id": c.case_id, "ticker": c.ticker, "role": c.history_cut.params["role"],
         "history_ends": c.history_cut.params["history_ends"],
         "effect": c.history_cut.params["effect"],
         "quarters_missing": c.history_cut.params["quarters_missing"]}
        for c in built if c.reported_quarters > 0 and c.history_cut is not None
    ]  # fmt: skip
    notes.append(_thin(n, "few_cases" if n < THIN_BELOW else "direction_not_recorded", cut))
    if event_type == "m_and_a":
        notes.append(MERGER_SHOCKS)
    notes += coverage
    missing = None
    if n == 0:
        missing = Coded(
            "no_cases",
            {"event_type": event_type, "as_of": as_of.isoformat(), "listed": len(built)},
            f"no past {event_type} case in the library has a quarter reported by {as_of}",
        )  # fmt: skip
    return PastEvents(
        ticker, event_type, as_of, default, rule_text(event_type),
        cases_sha256(CASES_PATH) if cases is None else "", metrics_sha256(), n, n_compared,
        len(built), thin, THIN_BELOW, built, [flagged(build(c)) for c in others],
        load_metrics()[event_type], notes, missing,
    )  # fmt: skip


# -- text --------------------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.1f}%"


def _money(value: float | None) -> str:
    return "–" if value is None else f"{value / 1e6:,.0f}"


def _case_lines(c: PastCase) -> list[str]:
    closeness = ("same company" if c.same_company else "other company") + ", " + (
        "same type" if c.same_type else f"other type ({c.event_type})")  # fmt: skip
    out = ["", f"### {c.case_id}: {c.description} ({closeness})", f"Source: {c.source_url}"]
    if c.scope_change:
        out.append(f"Scope change: {c.scope_change}")
    if c.history_cut:
        out.append(f"Filings cut: {c.history_cut.text}")
    if c.missing:
        return [*out, c.missing.text]
    out += [f"Forecast made on {c.run_as_of} (run {c.run_id}); millions",
            "| Quarter | h | Revenue forecast | Revenue actual | Miss | Usual median | Rank | "
            "Margin forecast | Margin actual | EBIT miss (pts) | Usual median | Rank |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for q in c.quarters:
        cells = []
        for name in ITEMS:
            it = q.items[name]
            u = it.usual
            if it.missing is not None:
                cells.append([it.missing.code, "–", "–"])
            elif u is not None and u.missing is not None and u.missing.code == "scope_change":
                cells.append([_pct(it.signed_miss), "scope change", "–"])
            elif u is not None and u.missing is not None and u.missing.code == "ended_before_event":
                cells.append([_pct(it.signed_miss), "pre-event", "–"])
            elif u is None:
                cells.append([_pct(it.signed_miss), "–", "–"])
            else:
                cells.append([_pct(it.signed_miss), _pct(u.median_miss), _pct(u.rank)])
        rev = q.items["revenue"]
        out.append(
            f"| {q.period} | {q.horizon} | {_money(rev.forecast)} | {_money(rev.actual)} | "
            f"{' | '.join(cells[0])} | {_pct(q.forecast_margin)} | {_pct(q.actual_margin)} | "
            f"{' | '.join(cells[1])} |"
        )
    return out


def render(p: PastEvents) -> str:
    when = " (the last day ended in New York)" if p.as_of_default else ""
    out = [f"Past {p.event_type} cases for a question about {p.ticker}, as of {p.as_of}{when}",
           f"Rule: {p.rule}.",
           f"n = {p.n} with a quarter reported ({p.n_compared} compared with the usual miss, "
           f"{p.n_listed} listed){'; thin evidence' if p.thin_evidence else ''}"]  # fmt: skip
    if p.missing:
        out += ["", p.missing.text]
    for c in p.cases:
        out += _case_lines(c)
    if p.same_company_other_type:
        out += ["", f"## {p.ticker}'s own cases of other types (context, not counted in n)"]
        for c in p.same_company_other_type:
            out += _case_lines(c)
    out += ["", "## Metrics to watch", "| Metric | Where | Source |", "|---|---|---|"]
    out += [f"| {m.metric} | {m.where_to_find} | {m.source} |" for m in p.metrics]
    out += ["", *[f"Note: {n.text}" for n in p.notes]]
    return "\n".join(out) + "\n"
