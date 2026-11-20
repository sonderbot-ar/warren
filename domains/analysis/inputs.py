"""The inputs behind an answer (backlog #471): each assumption a run's outputs reach, with its
history in the assumption's own measure, the parts behind each point and the points it used.

The student app draws a card per input ("cell") beside an answer: how the input moved over past
fiscal years, what each value is made of, and the run's assumption beside them. Every number
here is the engine's: ratio and growth points are the ones `reported_period` gives on the run's
own date (v0.9.6, the valuations' rules), same-filing growth is the pair the growth driver reads,
and the two new numbers (a quarter's contribution to annual growth, operating working capital
over revenue) go through `financial_math`. Read-only: nothing is stored and no run changes.

Point-in-time: every history value is read as known on the run's `as_of`.
"""

import sqlite3
import warnings
from dataclasses import asdict, dataclass, field
from datetime import date

from domains.analysis import dcf
from domains.analysis import financial_math as fm
from domains.analysis import sources as src
from domains.analysis.coded import Coded
from domains.analysis.reported import (
    LATEST_QUARTER,
    LATEST_YEAR,
    LENGTH_NOTE_DAYS,
    Line,
    Period,
    ReportedError,
    ReportedPeriod,
    _Filings,
    _plain,
    reported_period,
)
from domains.analysis.schemas import SINGLE, Assumption

YEARS_RANGE = (3, 10)  # filings go back to 2009
DEFAULT_YEARS = 5

# How a row was computed, as a closed list the app words (the English is the row's `method`)
METHOD_CODES = (
    "seed_quarter",  # the reported quarter itself
    "seed_year_times_share",  # the year × this quarter's share (quarters off the year)
    "same_filing_average_fading",  # 3-year same-filing average growth, fading to terminal
    "same_quarter_average",  # average margin of the same fiscal quarter, last 12 quarters
    "years_sum_ratio",  # Σ numerator ÷ Σ revenue (or pretax) over the history years
    "years_sum_ratio_kept_years",  # the same over the years kept (a loss or outside year left out)
    "statutory_tax_rate",  # the statutory rate: pretax income too small for an effective rate
    "year_end_average_ratio",  # average of each year-end's working capital ÷ that year's revenue
    "owner_choice",  # a row of user_assumptions.csv
    "single_value",  # a single value (rates, beta, balance-sheet items, shares)
)

GAPS = {
    "owner_choice": "An owner's choice (user_assumptions.csv): its history is the choice itself.",
    "history_not_built": "History for this single value is not built yet (backlog #476).",
    "computed_from_other_cells": "Computed from other cells of the run: see their cards.",
}

RATIO_CELLS = {  # cell -> (the reported ratio, its series measure)
    "tax_rate": "effective_tax_rate",
    "debt_tax_rate": "effective_tax_rate",
    "da_pct": "da_share",
    "capex_pct": "capex_share",
}
DRIVER_CELLS = {dcf.SEED, "revenue_growth", "operating_margin", "nwc_pct", *RATIO_CELLS}
# lines behind EBIT, shown as parts of a margin point when the period reports them
EBIT_PARTS = ("cost_of_revenue", "operating_expenses")


class InputsError(ValueError):
    """The question can't be answered: no such run, an output the run lacks, or a bad window.
    `code` and `params` say which, for the app (as the engine's refusals do)."""

    def __init__(self, message: str, code: str, params: dict):
        super().__init__(message)
        self.code, self.params = code, params


@dataclass(frozen=True)
class Part:
    """A line a point's value is made of, with its filing (or the filings it was derived from)."""

    name: str
    value: float
    period: str
    filing: dict | None  # the #140 Filing shape; None when derived
    derived: bool = False
    inputs: list[dict] = field(default_factory=list)  # filings of a derived line
    contribution: float | None = None  # a quarter's share of the year's growth (growth only)
    notes: list[Coded] = field(default_factory=list)  # e.g. a 14-week quarter, a mixed vintage


@dataclass(frozen=True)
class Point:
    period: str  # FY2024 or FY2024Q3
    # None on a calendar series (market data, balance dates): its `period` is then an ISO date
    # (2026-09-01) or a calendar year (2025)
    fiscal_year: int | None
    fiscal_period: str | None  # FY or Q1-Q4
    period_end: date | None
    value: float | None
    used: bool  # the cell's rows were computed from this point
    parts: list[Part] = field(default_factory=list)
    notes: list[Coded] = field(default_factory=list)
    missing: Coded | None = None
    # a fraction's two sums, in the filing's currency (not millions), and its formula (#477);
    # None on the seed, on growth and on the single values
    numerator: float | None = None
    base: float | None = None
    formula_id: str | None = None


@dataclass(frozen=True)
class Reference:
    """The assumption recomputed over the points the run used, as this chart reads them today
    (backlog #477), so the app can label the assumption's line and check it against the bars.

    `how` is `pooled` (Σ numerator ÷ Σ base: a larger year weighs more) or `mean` (each point
    counts the same). `simple_mean` is always the plain average of the same points, so the
    card can say why a pooled line is not where the bars' average would put it. `weights` are
    each point's weight in `value`, in the order of `periods` (pooled: its share of
    `base_sum`; mean: 1 ÷ the count). `rows` are the cell's rows computed from exactly these
    points (growth: the rows that hold the starting average, before the fade)."""

    method_code: str
    how: str  # pooled or mean
    value: float | None
    simple_mean: float | None
    periods: list[str]
    weights: list[float] | None
    numerator_sum: float | None  # pooled only, in the filing's currency
    base_sum: float | None
    numerator_code: str | None  # e.g. operating_income, income_tax (pooled only)
    base_code: str | None  # e.g. revenue, pretax_income
    rows: list[str]
    notes: list[Coded] = field(default_factory=list)


@dataclass(frozen=True)
class Series:
    measure: str  # e.g. revenue_growth_yoy, operating_margin, da_share
    frequency: str  # year, quarter, month (market data) or date (cover-page share counts)
    basis: str  # same_filing (both years from one 10-K) or latest (latest known on as_of)
    primary: bool  # the measure the assumption is computed on; the others are context
    fiscal_quarter: int | None  # a series of one fiscal quarter across years, else None
    points: list[Point]
    # about the series as a whole (`reported_series`): its revenue crosses a tag that changed
    # meaning (`series_mixes_meanings`, Exxon FY2016/FY2017) or a recast
    notes: list[Coded] = field(default_factory=list)
    # the assumption over this series' used points (#477): primary driver series only
    reference: Reference | None = None


@dataclass(frozen=True)
class CellRow:
    period: str
    value: float | None
    method_code: str
    used: list[str]  # the history points (period labels) the row was computed from


@dataclass(frozen=True)
class Cell:
    name: str
    rows: list[CellRow]
    history: list[Series]
    gap: Coded | None = None
    notes: list[Coded] = field(default_factory=list)


@dataclass(frozen=True)
class InputsBehind:
    run_id: str
    ticker: str
    as_of: date
    years: int
    outputs: list[dict]  # {name, period, value}: the outputs asked, with the run's values
    cells: list[Cell]

    def to_dict(self) -> dict:
        """Plain JSON types: dates as ISO text, numbers unrounded."""
        return _plain(asdict(self))


# -- which rows -----------------------------------------------------------------------------------


def reached_rows(trace: dict, outputs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The rows the outputs reach (as `sources.reaches`), in the order the formula first names
    them: the outputs in the order asked, each input in its formula's order, depth first."""
    seen_outputs: set = set()
    found: dict[tuple[str, str], None] = {}

    def walk(key):
        if key in seen_outputs:
            return
        seen_outputs.add(key)
        for ref in trace[key]["inputs"]:
            if ref["of"] == "row":
                found.setdefault((ref["name"], ref["period"]), None)
            else:
                walk((ref["name"], ref["period"]))

    for key in outputs:
        walk(key)
    return list(found)


def _method_code(name: str, row: Assumption, sources: list[dict], kept: list[str] | None) -> str:
    kinds = {s["kind"] for s in sources}
    if "owner_choice" in kinds:
        return "owner_choice"
    if name == dcf.SEED:
        filings = [s for s in sources if s["kind"] == "filing"]
        return "seed_year_times_share" if len(filings) > 1 else "seed_quarter"
    if name == "revenue_growth":
        return "same_filing_average_fading"
    if name == "operating_margin":
        return "years_sum_ratio" if row.period in dcf.YEARS else "same_quarter_average"
    if name in ("tax_rate", "debt_tax_rate"):
        if any(s["kind"] == "rule" and s.get("code") == "statutory_tax_rate" for s in sources):
            return "statutory_tax_rate"
        return "years_sum_ratio_kept_years" if kept else "years_sum_ratio"
    if name in ("da_pct", "capex_pct"):
        return "years_sum_ratio"
    if name == "nwc_pct":
        return "year_end_average_ratio"
    return "single_value"


def _used(
    name: str, row: Assumption, sources: list[dict], code: str, kept: list[str] | None
) -> list[str]:
    """The history points a row was computed from, read from its stored sources."""
    if code in ("owner_choice", "single_value", "statutory_tax_rate"):
        return []
    if name == dcf.SEED:
        return [row.period]
    if name == "revenue_growth":
        filings = [s for s in sources if s["kind"] == "filing"]
        return sorted({f"FY{s['fiscal_year']}" for s in filings[0::2]})  # (current, prior) pairs
    if code == "years_sum_ratio_kept_years":
        return sorted(kept or [])
    periods = {
        period
        for s in sources
        if s["kind"] == "derived"
        for ref in s["inputs"]
        if ref["name"].startswith("history:")
        for period in [ref["period"]]
    }
    return sorted(periods)


# -- the periods, read once -----------------------------------------------------------------------


class _Reader:
    """`reported_period` for each period a cell needs, on the run's date, each read once."""

    def __init__(self, conn: sqlite3.Connection, ticker: str, as_of: date):
        self.conn, self.ticker, self.as_of = conn, ticker, as_of
        self.cache: dict[str, ReportedPeriod | None] = {}
        self.shared: dict = {}  # reads `reported_period` keeps between periods

    def period(self, label: str) -> ReportedPeriod | None:
        if label not in self.cache:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")  # a run's own notes carry the warnings
                    self.cache[label] = reported_period(
                        self.conn, self.ticker, label, self.as_of, _shared=self.shared
                    )
            except ReportedError:
                self.cache[label] = None
        return self.cache[label]

    def latest(self, quarterly: bool) -> Period:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            answer = reported_period(
                self.conn,
                self.ticker,
                LATEST_QUARTER if quarterly else LATEST_YEAR,
                self.as_of,
                _shared=self.shared,
            )
        self.cache.setdefault(answer.period, answer)
        return Period(answer.fiscal_year, answer.fiscal_period)


def _label(year: int, fiscal_period: str) -> str:
    return f"FY{year}" + ("" if fiscal_period == "FY" else fiscal_period)


def _parse(label: str) -> tuple[int, str]:
    year, quarter = int(label[2:6]), label[6:]
    return year, quarter or "FY"


def _filing(f) -> dict | None:
    if f is None:
        return None
    out = asdict(f)
    out["filed_at"] = f.filed_at.isoformat() if f.filed_at else None
    return out


def _part(line: Line) -> Part:
    return Part(
        name=line.name,
        value=line.value,
        period=_label(line.fiscal_year, line.fiscal_period),
        filing=_filing(line.latest.filing),
        derived=line.derived,
        inputs=[_filing(f) for f in line.latest.inputs],
    )


NOT_REPORTED = "period_not_reported"


def _not_reported(label: str) -> Coded:
    return Coded(
        NOT_REPORTED,
        {"period": label},
        f"{label} was not reported by the run's date (a year or quarter not yet filed, or not "
        "in the company's filings)",
    )


def _line_notes(line: Line) -> list[Coded]:
    """The notes a reported line carries, plus a code when it is derived or changed."""
    notes = [n for n in (line.basis_note, line.meaning_note, line.tag_note) if n is not None]
    notes += [*line.sign_notes, *line.part_notes]
    if line.derived:
        notes.append(
            Coded(
                "derived_from_other_periods",
                {
                    "period": _label(line.fiscal_year, line.fiscal_period),
                    "inputs": [f.accession_no for f in line.latest.inputs],
                },
                "computed by Warren from other periods' filings (e.g. Q4 = the year − nine months)",
            )
        )
    return notes


def _empty(label: str, used: bool) -> Point:
    year, fp = _parse(label)
    return Point(label, year, fp, None, None, used, missing=_not_reported(label))


# -- the windows ----------------------------------------------------------------------------------


def _year_labels(last_year: int, years: int, used: set[str]) -> list[str]:
    """The last `years` fiscal years ending at `last_year`, and any used year before them."""
    labels = {f"FY{y}" for y in range(last_year - years + 1, last_year + 1)}
    labels |= {u for u in used if len(u) == 6}
    return sorted(labels)


def _quarter_labels(last: Period, years: int, used: set[str]) -> list[str]:
    index = last.fiscal_year * 4 + int(last.fiscal_period[1]) - 1
    labels = set()
    for i in range(index - years * 4 + 1, index + 1):
        labels.add(_label(i // 4, f"Q{i % 4 + 1}"))
    labels |= {u for u in used if len(u) == 8}
    return sorted(labels)


# -- the series -----------------------------------------------------------------------------------


def _ratio_point(reader: _Reader, label: str, ratio: str, used: bool, extra=()) -> Point:
    answer = reader.period(label)
    if answer is None:
        return _empty(label, used)
    r = answer.ratio(ratio)
    lines = {(x.name, _label(x.fiscal_year, x.fiscal_period)): x for x in answer.lines}
    lines |= {(x.name, _label(x.fiscal_year, x.fiscal_period)): x for x in answer.prior_lines}
    parts, notes = [], list(r.notes)
    for use in r.uses:
        line = lines.get((use["line"], use["period"]))
        if line is not None:
            parts.append(_part(line))
            notes += [n for n in _line_notes(line) if n not in notes]
    for name in extra if r.formula_id == "ebit_over_revenue" else ():  # parts of operating income
        line = answer.line(name)
        if line is not None and all(p.name != name for p in parts):
            parts.append(_part(line))
    return Point(
        label,
        answer.fiscal_year,
        answer.fiscal_period,
        answer.period_end,
        r.value,
        used,
        parts,
        notes,
        r.missing,
        r.numerator,
        r.base,
        r.formula_id,
    )


def _seed_point(reader: _Reader, label: str, used: bool) -> Point:
    answer = reader.period(label)
    line = answer.line("revenue") if answer else None
    if line is None:
        return _empty(label, used)
    return Point(
        label,
        line.fiscal_year,
        line.fiscal_period,
        line.period_end,
        line.value,
        used,
        [_part(line)],  # the line itself: its filing, or the filings a derived Q4 came from
        _line_notes(line),
    )


QUARTERS_OFF = "quarters_do_not_sum"


def _contributions(reader: _Reader, point: Point) -> Point:
    """A latest annual growth point with each fiscal quarter's contribution to it:
    (the quarter − the same quarter a year earlier) ÷ the year-earlier year. They add up to the
    year's growth only when the four quarters add up to both years; otherwise a note says by
    how much they miss."""
    if point.value is None:
        return point
    year = point.fiscal_year
    annual = reader.period(f"FY{year}")
    prior_year = next((x for x in annual.prior_lines if x.name == "revenue"), None)
    if prior_year is None or prior_year.value <= 0:
        return Point(
            **{
                **_fields(point),
                "notes": [
                    *point.notes,
                    Coded(
                        "contribution_prior_year_missing",
                        {"period": f"FY{year - 1}"},
                        f"FY{year - 1} revenue is not reported or not above zero: "
                        "no quarter contributions",
                    ),
                ],
            }
        )
    parts = list(point.parts)
    total = 0.0
    for q in range(1, 5):
        answer = reader.period(f"FY{year}Q{q}")
        now = answer.line("revenue") if answer else None
        before = (
            next((x for x in answer.prior_lines if x.name == "revenue"), None) if answer else None
        )
        if now is None or before is None:
            return Point(
                **{
                    **_fields(point),
                    "notes": [
                        *point.notes,
                        Coded(
                            "contribution_quarter_missing",
                            {"period": f"FY{year}Q{q}"},
                            f"FY{year}Q{q} or the same quarter a year earlier is not reported: "
                            "no quarter contributions",
                        ),
                    ],
                }
            )
        share = fm.growth_contribution(now.value, before.value, prior_year.value)
        total += share
        part_notes = [
            n
            for n in answer.ratio("revenue_growth_yoy").notes
            if n.code in ("period_length_differs", "mixed_vintage")
        ]
        parts.append(
            Part(
                name="revenue_quarter_contribution",
                value=fm.difference(now.value, before.value),
                period=f"FY{year}Q{q}",
                filing=_filing(now.latest.filing),
                derived=now.derived,
                inputs=[_filing(f) for f in now.latest.inputs],
                contribution=share,
                notes=part_notes,
            )
        )
    notes = list(point.notes)
    if abs(total - point.value) > 1e-9:
        rest = fm.difference(point.value, total)
        parts.append(
            Part(
                name="not_in_quarters",
                value=fm.contribution_amount(rest, prior_year.value),
                period=f"FY{year}",
                filing=None,
                contribution=rest,
            )
        )
        notes.append(
            Coded(
                QUARTERS_OFF,
                {"sum_of_contributions": total, "growth": point.value},
                f"the quarters' contributions add up to {total:+.2%}, not the year's "
                f"{point.value:+.2%}: the quarters do not add up to the years as filed",
            )
        )
    return Point(**{**_fields(point), "parts": parts, "notes": notes})


def _fields(point: Point) -> dict:
    return {f: getattr(point, f) for f in Point.__dataclass_fields__}


def _series_notes(reader: _Reader, labels: list[str]) -> list[Coded]:
    """`reported_series`'s notes on the periods of a series that were reported."""
    from domains.analysis.reported import _series_meaning_notes, _series_recast_notes

    answers = sorted(
        (a for a in (reader.period(x) for x in labels) if a is not None),
        key=lambda a: a.period_end,
    )
    if len(answers) < 2:
        return []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        conn, as_of, shared = reader.conn, reader.as_of, reader.shared
        return _series_meaning_notes(conn, answers, as_of, shared) + _series_recast_notes(
            conn, answers, as_of, shared
        )


def _same_filing_growth(
    conn: sqlite3.Connection, cik: str, as_of: date, labels: list[str], used: set[str], filings
) -> Series:
    from domains.fundamentals.facts import same_filing_annual_comparisons

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pairs = {
            c.fiscal_year: c for c in same_filing_annual_comparisons(conn, cik, "revenue", as_of)
        }
    points = []
    for label in labels:
        year = int(label[2:])
        c = pairs.get(year)
        if c is None or c.prior.value <= 0:
            missing = (
                _not_reported(label)
                if c is None
                else Coded(
                    "base_not_positive",
                    {"item": "revenue (prior)", "value": c.prior.value},
                    "the year-earlier revenue is not positive",
                )
            )
            points.append(Point(label, year, "FY", None, None, label in used, missing=missing))
            continue
        notes = []
        days = (c.current.period_end - c.current.period_start).days + 1
        prior_days = (c.prior.period_end - c.prior.period_start).days + 1
        if abs(days - prior_days) >= LENGTH_NOTE_DAYS:
            notes.append(
                Coded(
                    "period_length_differs",
                    {"days": days, "prior_days": prior_days},
                    f"the periods differ in length ({days} days against {prior_days}): a 53-week "
                    "year or a 14-week quarter",
                )
            )
        parts = [
            Part(
                "revenue",
                f.value,
                f"FY{f.fiscal_year}",
                _filing(filings.get(f.accession_no)),
            )
            for f in (c.current, c.prior)
        ]
        points.append(
            Point(
                label,
                year,
                "FY",
                c.current.period_end,
                fm.growth(c.current.value, c.prior.value),
                label in used,
                parts,
                notes,
            )
        )
    return Series("revenue_growth_yoy", "year", "same_filing", True, None, points)


NWC_FORMULA = "operating_nwc_over_revenue"


def _nwc_series(conn, cik: str, as_of: date, labels: list[str], used: set[str], filings) -> Series:
    """Year-end operating working capital ÷ the year's revenue, in the run's own definition."""
    from domains.analysis.math_engine import EngineError, _operating_nwc, load_history

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        history = load_history(conn, cik, as_of)
    points = []
    for label in labels:
        year = int(label[2:])
        get = history.year(year)
        revenue = get("revenue")
        if revenue is None:
            points.append(_empty(label, label in used))
            continue
        try:
            nwc, _method, facts, missing = _operating_nwc(get, label)
        except EngineError as e:
            code = Coded(e.code, e.params, str(e))
            points.append(Point(label, year, "FY", None, None, label in used, missing=code))
            continue
        parts = [
            Part(
                f.canonical_name,
                f.value,
                label,
                None if f.derived else _filing(filings.get(f.accession_no)),
                f.derived,
                [_filing(filings.get(a)) for a in f.inputs],
            )
            for f in [*facts, revenue]
        ]
        notes = (
            [
                Coded(
                    "counted_as_zero",
                    {"items": missing},
                    f"not in that year's annual report, counted as zero: {', '.join(missing)}",
                )
            ]
            if missing
            else []
        )
        if revenue.value <= 0:
            bad = Coded(
                "base_not_positive",
                {"item": "revenue", "value": revenue.value},
                "revenue is not positive",
            )
            points.append(Point(label, year, "FY", None, None, label in used, parts, notes, bad))
            continue
        points.append(
            Point(
                label,
                year,
                "FY",
                revenue.period_end,
                fm.ratio(nwc, revenue.value),
                label in used,
                parts,
                notes,
                None,
                nwc,
                revenue.value,
                NWC_FORMULA,
            )
        )
    return Series("operating_nwc_share", "year", "latest", True, None, points)


# -- what the run itself read ------------------------------------------------------------------

# a used point against the run's own `history:*` rows: (numerator, divisor) by cell
RUN_HISTORY = {
    "operating_margin": ("history:ebit", "history:revenue"),
    "tax_rate": ("history:tax", "history:pretax"),
    "debt_tax_rate": ("history:tax", "history:pretax"),
    "da_pct": ("history:d_and_a", "history:revenue"),
    "capex_pct": ("history:capex", "history:revenue"),
    "nwc_pct": ("history:nwc", "history:revenue"),
}


def _run_value(name: str, label: str, stored: dict, growth_filings: dict) -> float | None:
    """What the run itself read for a history point, from its stored rows; None if not stored."""
    if name == dcf.SEED:
        return stored.get((dcf.SEED, label))
    if name == "revenue_growth":
        pair = growth_filings.get(label)
        return fm.growth(*pair) if pair and pair[1] > 0 else None
    top, bottom = RUN_HISTORY[name]
    num, den = stored.get((top, label)), stored.get((bottom, label))
    if num is None or not den or den <= 0:
        return None
    return fm.ratio(num, den)


def _with_run_reads(cell: "Cell", stored: dict, growth_filings: dict, rules: int | None) -> "Cell":
    """Mark each used point whose value differs from what the run read (a run stored under
    older reading rules, or before a later filing restated the figure): `run_read_differently`
    with the run's own value, so the chart can show both."""
    from domains.analysis.reading_rules import READING_RULES_VERSION

    seed_shared = {r.period for r in cell.rows if r.method_code == "seed_year_times_share"}
    history = []
    for series in cell.history:
        points = []
        for p in series.points:
            if not (series.primary and p.used and p.value is not None) or p.period in seed_shared:
                points.append(p)
                continue
            run_value = _run_value(cell.name, p.period, stored, growth_filings)
            if run_value is None or abs(run_value - p.value) <= 1e-9 * max(1.0, abs(run_value)):
                points.append(p)
                continue
            note = Coded(
                "run_read_differently",
                {
                    "period": p.period,
                    "run_value": run_value,
                    "value": p.value,
                    "run_rules_version": rules,
                    "rules_version": READING_RULES_VERSION,
                },
                f"the run read {p.period} as {run_value:.6g}, not {p.value:.6g}: it was stored "
                "under other reading rules or before a filing changed the figure",
            )
            points.append(Point(**{**_fields(p), "notes": [*p.notes, note]}))
        history.append(Series(**{**_fields_of(series), "points": points}))
    return Cell(cell.name, cell.rows, history, cell.gap, cell.notes)


# -- the reference line (backlog #477) ------------------------------------------------------------

# how each method computes its rows from the history points
POOLED_METHODS = ("years_sum_ratio", "years_sum_ratio_kept_years")
MEAN_METHODS = ("same_quarter_average", "year_end_average_ratio", "same_filing_average_fading")
REFERENCE_HOW = ("pooled", "mean")
REFERENCE_NOTES = (
    "reference_point_missing",  # a used point has no value today: no line
    "reference_differs_from_run",  # the run's row differs (older rules, or a figure refiled)
    "reference_clipped",  # the row is the line held to the engine's bounds (tax 0%-50%)
    "reference_mixes_formulas",  # the used points divide different lines (e.g. two tax bases)
)
CLIPPED_CELLS = ("tax_rate", "debt_tax_rate")

# what each fraction divides: formula id -> (numerator code, base code), for the app to word
FORMULA_LINES = {
    "ebit_over_revenue": ("operating_income", "revenue"),
    "pretax_plus_interest_over_revenue": ("pretax_income_plus_interest", "revenue"),
    "capex_over_revenue": ("capex", "revenue"),
    "capex_over_revenue_fallback": ("capex", "revenue"),
    "d_and_a_over_revenue": ("d_and_a", "revenue"),
    "d_and_a_over_revenue_fallback": ("d_and_a", "revenue"),
    "tax_over_pretax": ("income_tax", "pretax_income"),
    "tax_over_pretax_by_region": ("income_tax", "pretax_income_by_region"),
    "tax_over_net_income_plus_tax": ("income_tax", "net_income_plus_tax"),
    NWC_FORMULA: ("operating_working_capital", "revenue"),
}


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a))


def _reference(cell: "Cell", series: Series) -> Reference | None:
    used = [p for p in series.points if p.used]
    periods = [p.period for p in used]
    rows = [
        r
        for r in cell.rows
        if r.method_code in (*POOLED_METHODS, *MEAN_METHODS) and set(r.used) == set(periods)
    ]
    if not used or not rows:
        return None  # an owner's choice, a what-if's own value, a statutory rate, the seed
    method = rows[0].method_code
    how = "pooled" if method in POOLED_METHODS else "mean"
    if method == "same_filing_average_fading":  # the rows that hold the start, before the fade
        first = rows[0].value
        rows = [r for r in rows if r.value is not None and first is not None and r.value == first]
        rows = rows or cell.rows[:1]
    formulas = {p.formula_id for p in used if p.formula_id is not None}
    codes = FORMULA_LINES.get(next(iter(formulas))) if len(formulas) == 1 else None
    numerator_code, base_code = codes if codes and how == "pooled" else (None, None)
    notes: list[Coded] = []
    value = simple = num_sum = base_sum = weights = None
    gaps = [
        p.period
        for p in used
        if p.value is None or (how == "pooled" and (p.numerator is None or p.base is None))
    ]
    if gaps:
        notes.append(
            Coded(
                "reference_point_missing",
                {"periods": gaps},
                f"no value today for {', '.join(gaps)}, a point the run used",
            )
        )
    else:
        values = [p.value for p in used]
        simple = fm.mean(values)
        if how == "pooled":
            nums, bases = [p.numerator for p in used], [p.base for p in used]
            if sum(bases) > 0:
                value = fm.pooled_ratio(nums, bases)
                num_sum, base_sum = sum(nums), sum(bases)
                weights = fm.base_shares(bases)
            else:
                notes.append(
                    Coded(
                        "reference_point_missing",
                        {"periods": periods},
                        "the bases of the points the run used do not sum to a positive figure",
                    )
                )
        else:
            value = simple
            weights = [1 / len(values)] * len(values)
    if len(formulas) > 1:
        notes.append(
            Coded(
                "reference_mixes_formulas",
                {"formula_ids": sorted(f for f in formulas if f)},
                "the points the run used do not all divide the same lines",
            )
        )
    if value is not None:
        off = [r for r in rows if r.value is not None and not _same(r.value, value)]
        if cell.name in CLIPPED_CELLS:
            from domains.analysis.math_engine import TAX_RATE_BOUNDS

            low, high = TAX_RATE_BOUNDS
            held = min(max(value, low), high)
            clipped = [r for r in off if held != value and _same(r.value, held)]
            if clipped:
                notes.append(
                    Coded(
                        "reference_clipped",
                        {
                            "rows": [r.period for r in clipped],
                            "run_value": held,
                            "value": value,
                            "low": low,
                            "high": high,
                        },  # fmt: skip
                        f"the history gives {value:.6g}; the run holds it to {held:.6g}, "
                        "inside the engine's bounds",
                    )
                )
            off = [r for r in off if r not in clipped]
        if off:
            notes.append(
                Coded(
                    "reference_differs_from_run",
                    {"rows": [r.period for r in off], "run_value": off[0].value, "value": value},
                    f"the run's {off[0].period} is {off[0].value:.6g}, not {value:.6g}: it was "
                    "stored under other reading rules, before a filing changed a figure, or "
                    "clipped to the engine's bounds",
                )
            )
    return Reference(
        method,
        how,
        value,
        simple,
        periods,
        weights,
        num_sum,
        base_sum,
        numerator_code,
        base_code,
        [r.period for r in rows],
        notes,
    )


def _with_references(cell: "Cell") -> "Cell":
    history = [
        Series(**{**_fields_of(s), "reference": _reference(cell, s)}) if s.primary else s
        for s in cell.history
    ]
    return Cell(cell.name, cell.rows, history, cell.gap, cell.notes)


def _fields_of(series: Series) -> dict:
    return {f: getattr(series, f) for f in Series.__dataclass_fields__}


def _growth_filings(stored_sources: dict) -> dict[str, tuple[float, float]]:
    """{FY label: (current, prior)} from the filings the growth rows name, as the run read them."""
    items = next(
        (v for (n, _p), v in stored_sources.items() if n == "revenue_growth"),
        [],
    )
    filings = [s for s in items if s["kind"] == "filing"]
    return {
        f"FY{cur['fiscal_year']}": (cur["value"], prior["value"])
        for cur, prior in zip(filings[0::2], filings[1::2], strict=True)
    }


# -- the call -------------------------------------------------------------------------------------


def inputs_behind(
    conn: sqlite3.Connection,
    run_id: str,
    outputs: list[tuple[str, str]],
    years: int = DEFAULT_YEARS,
) -> InputsBehind:
    """For the outputs an answer shows, every row of the run they reach, grouped by name in the
    formula's order, each with its history over `years` fiscal years as known on the run's date.

    Single values get their own history (backlog #476, `single_values.py`); owner choices come
    back with their rows and the gap `owner_choice`.
    """
    from domains.analysis.runs import load_assumptions, load_outputs

    if not YEARS_RANGE[0] <= years <= YEARS_RANGE[1]:
        low, high = YEARS_RANGE
        raise InputsError(
            f"years must be from {low} to {high}, got {years}",
            "years_out_of_range",
            {"years": years, "low": low, "high": high},
        )
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise InputsError(f"no run {run_id}", "run_not_found", {"run_id": run_id})
    rows = load_assumptions(conn, run_id)
    trace = src.output_trace(rows)
    asked = [tuple(o) for o in outputs]
    unknown = [o for o in asked if o not in trace]
    if not asked or unknown:
        raise InputsError(
            f"not an output of {run_id}: {unknown or 'none asked'}",
            "output_not_in_run",
            {"run_id": run_id, "outputs": [list(o) for o in unknown]},
        )
    values = load_outputs(conn, run_id)
    stored = src.load(conn, run_id)
    by_key = {(a.name, a.period): a for a in rows}
    as_of = date.fromisoformat(run["as_of"])
    reader = _Reader(conn, run["ticker"], as_of)
    filings = _Filings(conn, run["cik"])

    from domains.analysis.math_engine import KEPT_YEARS_NOTES
    from domains.analysis.runs import run_notes

    notes = run_notes(conn, run_id).notes
    kept = next((n.params["kept_years"] for n in notes if n.code in KEPT_YEARS_NOTES), None)
    tax_notes = [n for n in notes if n.code in (*KEPT_YEARS_NOTES, "tax_rate_clipped")]

    run_values = {(a.name, a.period): a.value for a in rows}
    growth_pairs = _growth_filings(stored)

    from domains.analysis.single_values import Singles

    singles = Singles(conn, run, as_of, years, stored, reader, filings)
    names: dict[str, list[Assumption]] = {}
    for key in reached_rows(trace, asked):
        names.setdefault(key[0], []).append(by_key[key])

    cells = []
    for name, reached in names.items():
        cell_rows = []
        for a in sorted(reached, key=lambda a: _period_order(a.period)):
            sources = stored.get((a.name, a.period), [])
            k = kept if name in ("tax_rate", "debt_tax_rate") else None
            code = _method_code(name, a, sources, k)
            cell_rows.append(CellRow(a.period, a.value, code, _used(name, a, sources, code, k)))
        cell = _cell(name, cell_rows, reader, run, years, filings, singles)
        if cell.gap is None and name in DRIVER_CELLS:  # single values check their own
            cell = _with_run_reads(cell, run_values, growth_pairs, run["reading_rules_version"])
            cell = _with_references(cell)
        if name in ("tax_rate", "debt_tax_rate") and tax_notes:
            cell = Cell(cell.name, cell.rows, cell.history, cell.gap, [*tax_notes, *cell.notes])
        cells.append(cell)
    return InputsBehind(
        run_id=run_id,
        ticker=run["ticker"],
        as_of=as_of,
        years=years,
        outputs=[{"name": n, "period": p, "value": values.get((n, p))} for n, p in asked],
        cells=cells,
    )


def _period_order(period: str):
    if period.startswith("FY"):
        return (0, period)
    return (1, period)


def _cell(
    name: str, cell_rows: list[CellRow], reader: _Reader, run, years: int, filings, singles=None
) -> Cell:
    codes = {r.method_code for r in cell_rows}
    if name not in DRIVER_CELLS:
        if codes != {"owner_choice"} and singles is not None:
            from domains.analysis.single_values import single_cell

            cell = single_cell(singles, name, cell_rows)
            if cell is not None:
                return cell
        gap = "owner_choice" if codes == {"owner_choice"} else "history_not_built"
        return Cell(name, cell_rows, [], Coded(gap, {"cell": name}, GAPS[gap]))
    used = {u for r in cell_rows for u in r.used}
    last_quarter = reader.latest(quarterly=True)
    # the fiscal year of the latest quarter, filed or not, so an unfiled year shows as missing
    last_year = max(reader.latest(quarterly=False).fiscal_year, last_quarter.fiscal_year)
    year_labels = _year_labels(last_year, years, used)
    quarter_labels = _quarter_labels(last_quarter, years, used)
    notes = []
    history: list[Series] = []

    if name == dcf.SEED:
        for q in sorted({int(r.period[-1]) for r in cell_rows}):
            # `years` points per fiscal quarter, ending at the seed's own quarter
            seed = next(r.period for r in cell_rows if r.period.endswith(f"Q{q}"))
            year = int(seed[2:6])
            labels = [f"FY{y}Q{q}" for y in range(year - years + 1, year + 1)]
            points = [_seed_point(reader, x, x in used) for x in labels]
            history.append(
                Series(
                    "revenue", "quarter", "latest", True, q, points, _series_notes(reader, labels)
                )
            )
    elif name == "revenue_growth":
        history.append(
            _same_filing_growth(reader.conn, run["cik"], reader.as_of, year_labels, used, filings)
        )
        annual = [
            _contributions(reader, _ratio_point(reader, x, "revenue_growth_yoy", False))
            for x in year_labels
        ]
        history.append(
            Series(
                "revenue_growth_yoy",
                "year",
                "latest",
                False,
                None,
                annual,
                _series_notes(reader, year_labels),
            )
        )
        quarterly = [_ratio_point(reader, x, "revenue_growth_yoy", False) for x in quarter_labels]
        history.append(
            Series(
                "revenue_growth_yoy",
                "quarter",
                "latest",
                False,
                None,
                quarterly,
                _series_notes(reader, quarter_labels),
            )
        )
    elif name == "operating_margin":
        quarter_rows = any(r.method_code == "same_quarter_average" for r in cell_rows)
        year_rows = any(r.method_code == "years_sum_ratio" for r in cell_rows)
        for q in range(1, 5):
            labels = [x for x in quarter_labels if x.endswith(f"Q{q}")]
            points = [
                _ratio_point(reader, x, "operating_margin", x in used, EBIT_PARTS) for x in labels
            ]
            history.append(
                Series(
                    "operating_margin",
                    "quarter",
                    "latest",
                    quarter_rows,
                    q,
                    points,
                    _series_notes(reader, labels),
                )
            )
        points = [
            _ratio_point(reader, x, "operating_margin", x in used, EBIT_PARTS) for x in year_labels
        ]
        history.append(
            Series(
                "operating_margin",
                "year",
                "latest",
                year_rows,
                None,
                points,
                _series_notes(reader, year_labels),
            )
        )
    elif name in RATIO_CELLS:
        statutory = codes == {"statutory_tax_rate"}
        if statutory:
            notes.append(
                Coded(
                    "assumption_not_from_history",
                    {"method_code": "statutory_tax_rate"},
                    "the statutory rate is used, not one read from this history",
                )
            )
        measure = RATIO_CELLS[name]
        points = [_ratio_point(reader, x, measure, x in used) for x in year_labels]
        history.append(
            Series(
                measure,
                "year",
                "latest",
                not statutory,
                None,
                points,
                _series_notes(reader, year_labels),
            )
        )
    elif name == "nwc_pct":
        nwc = _nwc_series(reader.conn, run["cik"], reader.as_of, year_labels, used, filings)
        history.append(
            Series(
                **{**asdict(nwc), "points": nwc.points, "notes": _series_notes(reader, year_labels)}
            )
        )
    return Cell(name, cell_rows, history, None, notes)


__all__ = [
    "SINGLE",
    "InputsBehind",
    "InputsError",
    "Reference",
    "inputs_behind",
    "reached_rows",
]
