"""Grid cases (M10): test dates chosen by a calendar rule, for every company in the universe.

The rule is fixed in docs/designs/m10-more-dates.md before any result is seen:

- pre-cutoff: the 15th of February, May, August and November from 2019-05-15 (mid-quarter for
  seven of the eight companies, just after most of them file their 10-Q, so the next quarter is
  still running), for every date before the first day of the earliest model cutoff month;
- post-cutoff: the 1st and the 15th of every month, for every date whose 7-day news window
  starts after the latest model cutoff month has ended;
- up to an end date (GRID_END), so a later run extends the grid under the same rule.

A company whose filings stop here (`history_ends`, universe.csv) gets the longest horizon, up to
4 quarters, that the coverage guard accepts (`harness.guard_coverage`, as M9's origins), and is
left out on a date where not even one quarter fits. The grid file is
written by `write_grid` and checked by `load_grid`, which regenerates it from the rule and fails
if the file differs, so no date can be added or dropped by hand.
"""

import calendar
import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from domains.evaluation.cases import CASES_PATH, COLUMNS, Case, CaseError, load_cases
from domains.evaluation.harness import FILING_LAG_DAYS, QUARTER_DAYS
from domains.fundamentals.universe import PHASE1_UNIVERSE, UniverseCompany
from shared_kernel.config import NODE_MODELS

GRID_PATH = Path(__file__).parent / "grid_cases.csv"
GRID_START = date(2019, 5, 15)  # the first mid-quarter 15th after SUPPORTED_FROM (2019-03-01)
PRE_MONTHS = (2, 5, 8, 11)
GRID_END = date(2026, 10, 15)  # the last date with a forecast quarter reported by nov.02.2026
WINDOW_DAYS = 7  # the news window: the 7 New York days ending on the date (nodes.NEWS_DAYS)
HORIZON = 4
PRE = "grid rule: mid-quarter 15th"
POST = "grid rule: post-cutoff 1st/15th"
DESCRIPTION = "Grid date: no event chosen"


@dataclass(frozen=True)
class GridDate:
    day: date
    post_cutoff: bool


def _cutoffs() -> list[date]:
    found = sorted({m.training_cutoff for m in NODE_MODELS.values() if m.training_cutoff})
    if not found:
        raise CaseError("no model training cutoff recorded (shared_kernel/config.py)")
    return found


def cutoff_month_start() -> date:
    """The first day of the earliest model cutoff month: pre-cutoff dates are before it."""
    first = _cutoffs()[0]
    return first.replace(day=1)


def cutoff_month_end() -> date:
    """The last day of the latest model cutoff month (cutoffs are month-only)."""
    last = _cutoffs()[-1]
    return last.replace(day=calendar.monthrange(last.year, last.month)[1])


def window_start(day: date) -> date:
    """The first New York day of the date's news window."""
    return day - timedelta(days=WINDOW_DAYS - 1)


def is_post_cutoff(day: date) -> bool:
    """True when the date's whole news window is after every model's cutoff month."""
    return window_start(day) > cutoff_month_end()


def is_pre_cutoff(day: date) -> bool:
    """True when the date is before the earliest model's cutoff month began."""
    return day < cutoff_month_start()


def _months(start: date, end: date):
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def grid_dates(end: date = GRID_END) -> list[GridDate]:
    """Every grid date up to `end`, oldest first."""
    out = []
    for y, m in _months(GRID_START.replace(day=1), end):
        first, mid = date(y, m, 1), date(y, m, 15)
        if m in PRE_MONTHS and GRID_START <= mid <= end and is_pre_cutoff(mid):
            out.append(GridDate(mid, False))
        for day in (first, mid):
            if day <= end and is_post_cutoff(day):
                out.append(GridDate(day, True))
    return out


def _horizon(company: UniverseCompany, day: date) -> int:
    """The longest horizon (up to 4) the coverage guard accepts on this date; 0 if none."""
    if company.history_ends is None:
        return HORIZON
    for h in range(HORIZON, 0, -1):
        reach = day + timedelta(days=QUARTER_DAYS * (h + 1) + FILING_LAG_DAYS)
        if reach < company.history_ends:
            return h
    return 0


def grid_cases(
    universe: list[UniverseCompany] | None = None, end: date = GRID_END
) -> tuple[list[Case], list[tuple[str, str]]]:
    """The grid cases, and the (case id, reason) of every company-date left out by rule."""
    universe = PHASE1_UNIVERSE if universe is None else universe
    cases, left_out = [], []
    for g in grid_dates(end):
        for company in universe:
            case_id = f"{company.ticker}_{g.day.isoformat()}"
            horizon = _horizon(company, g.day)
            if horizon == 0:
                left_out.append(
                    (case_id, f"no quarter fits before history_ends {company.history_ends}")
                )
                continue
            cases.append(
                Case(
                    case_id=case_id,
                    ticker=company.ticker,
                    event_date=g.day,
                    event_type="grid",
                    description=DESCRIPTION,
                    horizon_quarters=horizon,
                    selected_because=POST if g.post_cutoff else PRE,
                    source_url="",
                    scope_change="",
                )
            )
    return cases, left_out


def render(cases: list[Case]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(COLUMNS)
    for c in cases:
        writer.writerow([c.case_id, c.ticker, c.event_date.isoformat(), c.event_type,
                         c.description, c.horizon_quarters, c.selected_because, c.source_url,
                         c.scope_change])  # fmt: skip
    return buf.getvalue()


def shared_with_hand_picked(cases: list[Case], events_path: Path = CASES_PATH) -> list[str]:
    """Grid case ids that are also hand-picked cases (same company and date).

    They stay in the grid (dropping them would be a choice made after looking) and share the
    hand-picked case's run and AI answers, which are keyed by company and date; storing the grid
    never overwrites the hand-picked row (`cases.store_cases`).
    """
    hand_cases = load_cases(events_path)
    if any(c.is_grid for c in hand_cases):
        raise CaseError(f"{events_path.name} holds grid cases: they belong in the grid file only")
    hand = {c.case_id for c in hand_cases}
    return sorted(c.case_id for c in cases if c.case_id in hand)


def write_grid(
    path: Path = GRID_PATH,
    universe: list[UniverseCompany] | None = None,
    end: date = GRID_END,
    events_path: Path = CASES_PATH,
) -> list[Case]:
    cases, _ = grid_cases(universe, end)
    shared_with_hand_picked(cases, events_path)
    path.write_text(render(cases))
    return cases


def load_grid(
    path: Path = GRID_PATH,
    universe: list[UniverseCompany] | None = None,
    end: date = GRID_END,
    events_path: Path = CASES_PATH,
) -> list[Case]:
    """The grid file's cases, after checking it is exactly what the rule generates."""
    expected, _ = grid_cases(universe, end)
    if path.read_text() != render(expected):
        raise CaseError(
            f"{path.name} is not what the grid rule generates: run "
            "`python -m domains.evaluation grid --write` (never edit it by hand)"
        )
    tickers = {c.ticker for c in (PHASE1_UNIVERSE if universe is None else universe)}
    cases = load_cases(path, tickers=tickers)
    if any(not c.is_grid for c in cases):
        raise CaseError(f"{path.name} holds a case that is not a grid case")
    shared_with_hand_picked(cases, events_path)
    return cases
