"""A hindsight re-score of the M9 monthly forecasts on the fresh runs (backlog #633).

v0.10.60 built a fresh baseline under today's reading rules for every stored date. The
evaluation keeps scoring the runs of the time: that is the record of what Warren said, and
today's rules were written after seeing those dates' errors, so a score on the fresh runs is not
out of sample. This module scores each M9 origin's fresh run with the M9 code itself, beside the
stored miss of the run of the time, against the same first-reported actuals, and says how much
the reading fixes moved the error. Every result is labelled "scored with today's rules
(hindsight)". Nothing is stored: the result is a pure function of stored runs and filings.

Errors are M9's: revenue as ln(actual / forecast), operating profit (EBIT) in margin points of
actual revenue. A quarter is compared only when both rows are `ok`, for the same period and
item, with the same actual and actual revenue.
Design: docs/designs/backlog-633-hindsight-rescore.md.
"""

import sqlite3
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from domains.analysis.reading_rules import READING_RULES_VERSION
from domains.evaluation.harness import evaluate_case, scoring_errors
from domains.evaluation.ranges import error_rows, origin_case
from domains.fundamentals.concepts import concept_map_sha256
from shared_kernel.calendar import last_ended_day

LABEL = "Scored with today's rules (hindsight)"
ITEMS = ("revenue", "ebit")
MOVED = 1e-9  # an error that changed by more than this moved

# The newest baseline of a company and date under today's reading rules and concept map, as the
# app and `fresh_runs` pick a baseline: no parent, no seed, no LLM-proposed row.
_FRESH = """
    SELECT r.run_id FROM runs r
    WHERE r.ticker = ? AND r.as_of = ? AND r.parent_run_id IS NULL AND r.seed IS NULL
      AND r.reading_rules_version = ? AND r.concept_map_sha256 = ?
      AND NOT EXISTS (SELECT 1 FROM assumptions a
                      WHERE a.run_id = r.run_id AND a.source = 'llm_proposed')
    ORDER BY r.created_at DESC, r.run_id DESC LIMIT 1
"""


@dataclass(frozen=True)
class Pair:
    """One forecast quarter scored on both runs."""

    origin_id: str
    ticker: str
    horizon: int
    period: str
    item: str
    old_error: float  # the run of the time, scored today
    new_error: float  # the fresh run, scored today

    @property
    def change(self) -> float:
        return self.new_error - self.old_error


@dataclass
class Rescore:
    actuals_as_of: date
    pairs: list[Pair] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)  # reason -> origins or quarters
    failed: list[tuple[str, str]] = field(default_factory=list)  # (origin_id, error)
    origins: int = 0  # ok origins looked at
    rescored: int = 0  # origins whose two runs were scored
    stored_drift: int = 0  # stored misses that differ from the run of the time scored today

    def skip(self, reason: str, n: int = 1) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + n


def _same(a, b) -> bool:
    """Two actuals (US$) agree to the cent, or are both missing."""
    return a is None and b is None or (a is not None and b is not None and abs(a - b) < 0.005)


def compare(oid: str, ticker: str, old: list[dict], fresh: list[dict], out: Rescore) -> None:
    """Pair the run of the time's error rows with the fresh run's, by quarter and item.

    Keyed on the period, not the horizon: a fresh run that reads one more filed quarter
    forecasts the same period at a shorter horizon; the pair keeps the old run's horizon."""
    by_key = {(r["period"], r["item"]): r for r in fresh}
    for s in old:
        f = by_key.get((s["period"], s["item"]))
        if s["status"] != "ok":
            out.skip("quarter not ok on the run of the time (missing or excluded)")
        elif f is None or f["status"] != "ok":
            out.skip("quarter not ok or not forecast on the fresh run")
        elif not (
            _same(s["actual"], f["actual"]) and _same(s["actual_revenue"], f["actual_revenue"])
        ):
            out.skip("actual differs")
        else:
            out.pairs.append(
                Pair(oid, ticker, s["horizon"], s["period"], s["item"], s["error"], f["error"])
            )


def _drift(stored: list, live: list[dict]) -> int:
    """Quarters whose stored miss differs from the run of the time scored again today."""
    by_key = {(r["period"], r["item"]): r for r in live}
    n = 0
    for s in stored:
        r = by_key.get((s["period"], s["item"]))
        if r is None or r["status"] != s["status"]:
            n += 1
        elif s["status"] == "ok" and abs(r["error"] - s["error"]) > MOVED:
            n += 1
    return n


def hindsight_rescore(
    conn: sqlite3.Connection,
    tickers: Iterable[str] | None = None,
    actuals_as_of: date | None = None,
) -> Rescore:
    """Score every ok M9 origin's run of the time and its fresh run, both today and against the
    same first-reported actuals, quarter by quarter. Reads only; writes nothing.

    Both sides are scored live, as `ranges.reproduce_build` does, so the actuals come from the
    same reading code on both; how many stored misses differ from the live score of the run of
    the time is counted apart (`stored_drift`)."""
    wanted = None if tickers is None else {t.upper() for t in tickers}
    actuals_as_of = actuals_as_of or last_ended_day(datetime.now(UTC))
    out = Rescore(actuals_as_of)
    today_map = concept_map_sha256()
    origins = conn.execute("SELECT * FROM forecast_origins ORDER BY ticker, as_of").fetchall()
    for o in origins:
        if wanted is not None and o["ticker"] not in wanted:
            continue
        fresh = conn.execute(
            _FRESH, (o["ticker"], o["as_of"], READING_RULES_VERSION, today_map)
        ).fetchone()
        if o["status"] != "ok":
            out.skip("origin failed when built" + ("" if fresh is None else ", has a fresh run"))
            continue
        out.origins += 1
        if fresh is None:
            out.skip("origin: no fresh run under today's rules")
            continue
        if fresh["run_id"] == o["run_id"]:
            out.skip("origin: its own run is already under today's rules")
            continue
        as_of, oid = date.fromisoformat(o["as_of"]), o["origin_id"]
        case = origin_case(o["ticker"], as_of)
        try:
            _, old_rows = evaluate_case(conn, case, actuals_as_of=actuals_as_of, run_id=o["run_id"])
            _, new_rows = evaluate_case(
                conn, case, actuals_as_of=actuals_as_of, run_id=fresh["run_id"]
            )
        except scoring_errors() as e:
            out.failed.append((oid, str(e)))
            continue
        out.rescored += 1
        old = error_rows(oid, o["ticker"], as_of, old_rows)
        stored = conn.execute(
            "SELECT * FROM baseline_errors WHERE origin_id = ?", (oid,)
        ).fetchall()
        out.stored_drift += _drift(stored, old)
        compare(oid, o["ticker"], old, error_rows(oid, o["ticker"], as_of, new_rows), out)
    return out


# -- summary -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    ticker: str  # or "All"
    item: str
    n: int
    moved: int
    old_mae: float
    new_mae: float
    old_median: float
    new_median: float
    quarters: int  # distinct (company, period): one quarter is forecast from several origins
    better: int  # moved quarters whose absolute error fell
    worse: int  # moved quarters whose absolute error rose
    moved_change: float | None  # mean change of absolute error on the moved quarters only

    @property
    def change(self) -> float:
        return self.new_mae - self.old_mae


def _line(ticker: str, item: str, pairs: list[Pair]) -> Line | None:
    if not pairs:
        return None
    old = [abs(p.old_error) for p in pairs]
    new = [abs(p.new_error) for p in pairs]
    moved = [abs(p.new_error) - abs(p.old_error) for p in pairs if abs(p.change) > MOVED]
    return Line(
        ticker, item, len(pairs), len(moved),
        statistics.fmean(old), statistics.fmean(new),
        statistics.median(old), statistics.median(new),
        len({(p.ticker, p.period) for p in pairs}),
        sum(d < 0 for d in moved), sum(d > 0 for d in moved),
        statistics.fmean(moved) if moved else None,
    )  # fmt: skip


def summary(result: Rescore) -> list[Line]:
    """Per company and item, then pooled ("All"), in that order."""
    lines = []
    tickers = sorted({p.ticker for p in result.pairs})
    for item in ITEMS:
        for t in [*tickers, "All"]:
            ps = [p for p in result.pairs if p.item == item and (t == "All" or p.ticker == t)]
            line = _line(t, item, ps)
            if line is not None:
                lines.append(line)
    return lines


def by_horizon(result: Rescore) -> list[Line]:
    """Pooled across companies, per item and horizon (h1 and h4 errors are not alike)."""
    lines = []
    for item in ITEMS:
        for h in sorted({p.horizon for p in result.pairs}):
            ps = [p for p in result.pairs if p.item == item and p.horizon == h]
            line = _line(f"h{h}", item, ps)
            if line is not None:
                lines.append(line)
    return lines


def largest(result: Rescore, n: int = 2) -> list[Pair]:
    """The `n` largest moves of each company, by absolute change of the error, companies in
    order; ties by origin, horizon and item."""
    out = []
    for t in sorted({p.ticker for p in result.pairs}):
        ps = [p for p in result.pairs if p.ticker == t and abs(p.change) > MOVED]
        out += sorted(ps, key=lambda p: (-abs(p.change), p.origin_id, p.horizon, p.item))[:n]
    return out


# -- report ------------------------------------------------------------------------------------

_ITEM_NAME = {
    "revenue": "Revenue (error in %, log ratio)",
    "ebit": "Operating profit (error in margin points)",
}


def _shown(item: str, x: float) -> str:
    return f"{100 * x:.2f}"


def report(result: Rescore) -> str:
    lines = [
        f"# {LABEL}: the M9 monthly forecasts on the fresh runs",
        "",
        "This is not Warren's forecast record. The record is the evaluation of the runs of the time"
        " (`baseline_errors`, `eval_results`), which this report does not change. Today's reading"
        " rules were written after seeing these dates' errors, so a score on runs read under them"
        " is not out of sample: it says how much the reading fixes moved the error on dates they"
        " were partly found on, not how well today's method forecasts.",
        "",
        f"Actuals as first reported, as known on {result.actuals_as_of.isoformat()}. A quarter is"
        " compared only when both runs scored it, with the same actual. Errors are absolute;"
        " revenue in % (100 × |ln(actual / forecast)|), operating profit in margin points.",
        "",
        "No significance test is run. Today's rules were chosen after seeing these errors, so a"
        " test of equal accuracy (Diebold and Mariano 1995) would not hold its stated size"
        " (Diebold 2015; White 2000), and monthly origins forecast the same quarters again and"
        " again, so the rows are far from independent: the distinct quarters are counted beside"
        " them. The numbers below describe the change; they do not test it.",
        "",
        f"Origins looked at: {result.origins}; re-scored on a fresh run: {result.rescored};"
        f" failed: {len(result.failed)}; quarters compared: {len(result.pairs)}. Stored misses"
        f" that differ from the run of the time scored again today: {result.stored_drift} (the"
        " comparison scores both runs today, so these do not enter it).",
        "",
    ]
    for item in ITEMS:
        rows = [x for x in [*summary(result), *by_horizon(result)] if x.item == item]
        if not rows:
            continue
        lines += [
            f"## {_ITEM_NAME[item]}: {LABEL}",
            "",
            "| Company or horizon | Rows | Distinct quarters | Moved (better / worse) |"
            " Mean, run of the time | Mean, fresh run | Change | Change on moved rows |"
            " Median, run of the time | Median, fresh run |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for x in rows:
            on_moved = "" if x.moved_change is None else f"{100 * x.moved_change:+.2f}"
            lines.append(
                f"| {x.ticker} | {x.n} | {x.quarters} | {x.moved} ({x.better} / {x.worse}) |"
                f" {_shown(item, x.old_mae)} | {_shown(item, x.new_mae)} | {100 * x.change:+.2f} |"
                f" {on_moved} | {_shown(item, x.old_median)} | {_shown(item, x.new_median)} |"
            )
        lines.append("")
    big = largest(result)
    if big:
        lines += [
            f"## Largest moves of each company: {LABEL}",
            "",
            "| Origin | Quarter | Item | Error, run of the time | Error, fresh run |",
            "|---|---|---|---|---|",
        ]
        for p in big:
            lines.append(
                f"| {p.origin_id} | {p.period} (h{p.horizon}) | {p.item} |"
                f" {100 * p.old_error:+.2f} | {100 * p.new_error:+.2f} |"
            )
        lines.append("")
    if result.skipped:
        lines += ["## Not compared", ""]
        lines += [f"- {reason}: {n}" for reason, n in sorted(result.skipped.items())]
        lines.append("")
    if result.failed:
        lines += ["## Fresh runs that could not be scored", ""]
        lines += [f"- {oid}: {err}" for oid, err in result.failed]
        lines.append("")
    return "\n".join(lines)


def write_report(result: Rescore, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report(result), encoding="utf-8")
    return path
