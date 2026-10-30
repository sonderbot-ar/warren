"""Point-in-time fact queries: what a company had reported as of a given date.

For each canonical item and period, the value is the newest version (public on the as-of date) of
the highest-priority tag that reports the period. In first_reported mode it is the earliest filing,
and the highest-priority tag within it. `restated` means the value differs from first_reported.

Quarterly results add the quarters companies never report on their own (Q4, and standalone Q2/Q3
for cash-flow items reported only year-to-date). They are derived at query time from the inputs
selected for that as-of date, so a derived value is never built from a number not yet public.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from domains.fundamentals.schemas import Fact
from domains.fundamentals.universe import warn_if_beyond_history

Mode = Literal["latest", "first_reported"]
Frequency = Literal["reported", "quarterly", "annual"]

# Only additive flows can be derived by subtraction. Weighted-average shares are averages:
# FY minus nine months of an average means nothing, so those quarters stay unreported.
DERIVABLE_UNITS = {"USD"}

QUERY = """
SELECT f.*, c.canonical_name, c.priority
FROM financial_facts f JOIN concepts c USING (xbrl_concept)
WHERE f.cik = ? AND f.filed_at <= ? AND c.canonical_name IN ({placeholders})
"""


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _best_in_filing(rows: list[sqlite3.Row]) -> sqlite3.Row:
    return min(rows, key=lambda r: r["priority"])


def _to_fact(row: sqlite3.Row, restated: bool) -> Fact:
    return Fact(
        canonical_name=row["canonical_name"],
        xbrl_concept=row["xbrl_concept"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        fiscal_year=row["fiscal_year"],
        fiscal_period=row["fiscal_period"],
        value=row["value"],
        unit=row["unit"],
        accession_no=row["accession_no"],
        filed_at=row["filed_at"],
        restated=restated,
    )


def _rows_by_period(
    conn: sqlite3.Connection, cik: str, canonical_names: list[str], as_of: date | str
) -> dict[tuple, dict[str, list[sqlite3.Row]]]:
    """(name, start, end) -> accession -> rows (one per tag that filing used), public on as_of."""
    known = {r[0] for r in conn.execute("SELECT DISTINCT canonical_name FROM concepts")}
    unknown = sorted(set(canonical_names) - known)
    if unknown:
        raise ValueError(f"Not in the concept map: {unknown}")
    periods: dict[tuple, dict[str, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    if not canonical_names:
        return periods

    warn_if_beyond_history(cik, _as_date(as_of))
    sql = QUERY.format(placeholders=", ".join("?" * len(canonical_names)))
    params = [cik, _as_date(as_of).isoformat(), *canonical_names]
    for row in conn.execute(sql, params):
        key = (row["canonical_name"], row["period_start"] or "", row["period_end"])
        periods[key][row["accession_no"]].append(row)
    return periods


def _filing_order(filings: dict[str, list[sqlite3.Row]]) -> list[str]:
    return sorted(filings, key=lambda accn: (filings[accn][0]["filed_at"], accn))


def get_reported_facts(
    conn: sqlite3.Connection,
    cik: str,
    canonical_names: list[str],
    as_of: date | str,
    mode: Mode = "latest",
) -> list[Fact]:
    """Every reported period for the requested items, exactly as known on `as_of` (inclusive)."""
    if mode not in ("latest", "first_reported"):
        raise ValueError(f"Unknown mode: {mode!r}")
    periods = _rows_by_period(conn, cik, canonical_names, as_of)

    facts = []
    for key in sorted(periods):
        filings = periods[key]
        first = _best_in_filing(filings[_filing_order(filings)[0]])
        if mode == "first_reported":
            facts.append(_to_fact(first, restated=False))
        else:
            latest = _latest_of_best_tag([row for rows in filings.values() for row in rows])
            facts.append(_to_fact(latest, restated=latest["value"] != first["value"]))
    return facts


def _latest_of_best_tag(rows: list[sqlite3.Row]) -> sqlite3.Row:
    """The newest version of the highest-priority tag that reports this period.

    Ranking the tag before the filing stops definition drift: later filings often repeat an old
    period under a broader or narrower tag (e.g. cash including restricted cash, on the cash-flow
    statement), which is a different measure, not a restatement. A restatement filed under a
    higher-ranked tag still wins, because that tag is preferred.
    """
    best = min(r["priority"] for r in rows)
    return max(
        (r for r in rows if r["priority"] == best), key=lambda r: (r["filed_at"], r["accession_no"])
    )


def newest_filing_disagreements(
    conn: sqlite3.Connection, cik: str, canonical_names: list[str], as_of: date | str
) -> list[tuple[Fact, Fact]]:
    """Periods where the newest filing's value differs from the selected one: (selected, newest).

    Under best-tag-first selection this happens when the newest filing reports a period only under
    a lower-ranked tag. Usually that is a different measure (definition drift, correctly ignored),
    but it can be a restatement filed only under that tag, which the selection rule would miss.
    """
    pairs = []
    periods = _rows_by_period(conn, cik, canonical_names, as_of)
    for key in sorted(periods):
        filings = periods[key]
        rows = [row for rows in filings.values() for row in rows]
        selected = _latest_of_best_tag(rows)
        newest = _best_in_filing(filings[_filing_order(filings)[-1]])
        if newest["value"] != selected["value"]:
            pairs.append((_to_fact(selected, restated=False), _to_fact(newest, restated=False)))
    return pairs


@dataclass(frozen=True)
class AnnualComparison:
    """A 10-K's current fiscal year against the prior year, both as reported in that filing."""

    fiscal_year: int
    current: Fact
    prior: Fact

    @property
    def growth(self) -> float:
        return self.current.value / self.prior.value - 1


def same_filing_annual_comparisons(
    conn: sqlite3.Connection, cik: str, canonical_name: str, as_of: date | str
) -> list[AnnualComparison]:
    """Year-on-year pairs from each annual report, newest fiscal year first.

    Both years come from one filing (its best tag for each), so each pair sits on one restatement
    basis: growth isn't distorted by a restated year next to an unrestated one. An amended 10-K
    replaces the original for its fiscal year.
    """
    by_filing: dict[str, dict[tuple, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    for (_name, start, end), filings in _rows_by_period(conn, cik, [canonical_name], as_of).items():
        for accn, rows in filings.items():
            if rows[0]["form"].startswith("10-K") and rows[0]["fiscal_period"] == "FY" and start:
                by_filing[accn][(start, end)].extend(rows)

    newest: dict[int, tuple[str, AnnualComparison]] = {}
    for accn, periods in by_filing.items():
        rows = sorted((_best_in_filing(r) for r in periods.values()), key=lambda r: r["period_end"])
        if len(rows) < 2 or rows[-1]["fiscal_year"] != rows[-2]["fiscal_year"] + 1:
            continue
        pair = AnnualComparison(
            rows[-1]["fiscal_year"], _to_fact(rows[-1], False), _to_fact(rows[-2], False)
        )
        filed = (rows[-1]["filed_at"], accn)
        if pair.fiscal_year not in newest or filed > newest[pair.fiscal_year][0]:
            newest[pair.fiscal_year] = (filed, pair)
    return [newest[y][1] for y in sorted(newest, reverse=True)]


# -- quarterly and annual views ---------------------------------------------------------------


def _derive(minuend: Fact, subtrahends: list[Fact], fiscal_period: str) -> Fact:
    """minuend − sum(subtrahends), e.g. Q4 = FY − M9. Public only once every input is."""
    inputs = [minuend, *subtrahends]
    restated = [f.restated for f in inputs]
    tags = list(dict.fromkeys(f.xbrl_concept for f in inputs))
    return Fact(
        canonical_name=minuend.canonical_name,
        xbrl_concept=" − ".join(tags),
        period_start=max(f.period_end for f in subtrahends) + timedelta(days=1),
        period_end=minuend.period_end,
        fiscal_year=minuend.fiscal_year,
        fiscal_period=fiscal_period,
        value=minuend.value - sum(f.value for f in subtrahends),
        unit=minuend.unit,
        filed_at=max(f.filed_at for f in inputs),
        restated=any(restated),
        derived=True,
        inputs=list(dict.fromkeys(a for f in inputs for a in (f.inputs or [f.accession_no]))),
        mixed_vintage=any(restated) and not all(restated),
    )


def _quarters_for_flow(year: dict[str, Fact], earliest: bool = False) -> list[Fact]:
    """Standalone Q1-Q4 for one fiscal year of a duration item, reported where possible.

    With `earliest` (first_reported mode), a quarter reported on its own only in a later filing
    (e.g. a Q4 recast in the next 10-K) gives way to its derivation if that was public first.
    """
    q = {p: year[p] for p in ("Q1", "Q2", "Q3", "Q4") if p in year}

    def place(period: str, minuend: str, subtrahends: list[Fact]) -> None:
        derived = _derive(year[minuend], subtrahends, period)
        if period not in q or (earliest and derived.filed_at < q[period].filed_at):
            q[period] = derived

    if year and next(iter(year.values())).unit in DERIVABLE_UNITS:
        if (earliest or "Q2" not in q) and {"H1", "Q1"} <= year.keys():
            place("Q2", "H1", [q["Q1"]])
        if (earliest or "Q3" not in q) and "M9" in year:
            if "H1" in year:
                place("Q3", "M9", [year["H1"]])
            elif {"Q1", "Q2"} <= q.keys():
                place("Q3", "M9", [q["Q1"], q["Q2"]])
        if (earliest or "Q4" not in q) and "FY" in year:
            if "M9" in year:
                place("Q4", "FY", [year["M9"]])
            elif {"Q1", "Q2", "Q3"} <= q.keys():
                place("Q4", "FY", [q["Q1"], q["Q2"], q["Q3"]])
    return [q[p] for p in ("Q1", "Q2", "Q3", "Q4") if p in q]


def _one_per_period(facts: list[Fact]) -> list[Fact]:
    """One fact per (item, fiscal year, fiscal period); unplaced facts are dropped.

    Two dated facts can share a label: an amended filing's cover page repeats shares outstanding
    under a later date, and rarely two balance-sheet dates fall in one period. The later one wins.
    """
    best: dict[tuple, Fact] = {}
    for fact in facts:
        if fact.fiscal_year is None:
            continue  # periods that couldn't be placed in the fiscal calendar
        key = (fact.canonical_name, fact.fiscal_year, fact.fiscal_period, fact.period_start is None)
        if key not in best or fact.period_end > best[key].period_end:
            best[key] = fact
    return list(best.values())


def _quarterly(facts: list[Fact], earliest: bool = False) -> list[Fact]:
    years: dict[tuple, dict[str, Fact]] = defaultdict(dict)
    quarters = []
    for fact in _one_per_period(facts):
        if fact.period_start is None:  # balance-sheet item: the Q4 balance is the year-end one
            if fact.fiscal_period == "FY":
                fact = fact.model_copy(update={"fiscal_period": "Q4"})
            quarters.append(fact)
        else:
            years[(fact.canonical_name, fact.fiscal_year)][fact.fiscal_period] = fact
    for year in years.values():
        quarters.extend(_quarters_for_flow(year, earliest))
    return sorted(quarters, key=lambda f: (f.canonical_name, f.period_end))


def get_facts(
    conn: sqlite3.Connection,
    cik: str,
    canonical_names: list[str],
    as_of: date | str,
    mode: Mode = "latest",
    frequency: Frequency = "reported",
) -> list[Fact]:
    """Point-in-time facts.

    frequency="reported": every period as filed (Q1-Q4, H1, M9, FY).
    frequency="annual":   fiscal years only (FY durations and year-end balances).
    frequency="quarterly": standalone quarters Q1-Q4, deriving the ones not reported. In
                           first_reported mode each quarter is the version public first.
    """
    facts = get_reported_facts(conn, cik, canonical_names, as_of, mode)
    if frequency == "reported":
        return facts
    if frequency == "annual":
        annual = _one_per_period([f for f in facts if f.fiscal_period == "FY"])
        return sorted(annual, key=lambda f: (f.canonical_name, f.period_end))
    if frequency == "quarterly":
        return _quarterly(facts, earliest=mode == "first_reported")
    raise ValueError(f"Unknown frequency: {frequency!r}")
