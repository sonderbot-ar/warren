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
from datetime import date, timedelta
from typing import Literal

from domains.fundamentals.schemas import Fact

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
    known = {r[0] for r in conn.execute("SELECT DISTINCT canonical_name FROM concepts")}
    unknown = sorted(set(canonical_names) - known)
    if unknown:
        raise ValueError(f"Not in the concept map: {unknown}")
    if not canonical_names:
        return []

    sql = QUERY.format(placeholders=", ".join("?" * len(canonical_names)))
    params = [cik, _as_date(as_of).isoformat(), *canonical_names]

    # (name, start, end) -> accession -> rows (one per tag that filing used)
    periods: dict[tuple, dict[str, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    for row in conn.execute(sql, params):
        key = (row["canonical_name"], row["period_start"] or "", row["period_end"])
        periods[key][row["accession_no"]].append(row)

    facts = []
    for key in sorted(periods):
        filings = periods[key]
        order = sorted(filings, key=lambda accn: (filings[accn][0]["filed_at"], accn))
        first = _best_in_filing(filings[order[0]])
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


def _quarters_for_flow(year: dict[str, Fact]) -> list[Fact]:
    """Standalone Q1-Q4 for one fiscal year of a duration item, reported where possible."""
    q = {p: year[p] for p in ("Q1", "Q2", "Q3", "Q4") if p in year}
    if year and next(iter(year.values())).unit in DERIVABLE_UNITS:
        if "Q2" not in q and {"H1", "Q1"} <= year.keys():
            q["Q2"] = _derive(year["H1"], [q["Q1"]], "Q2")
        if "Q3" not in q and "M9" in year:
            if "H1" in year:
                q["Q3"] = _derive(year["M9"], [year["H1"]], "Q3")
            elif {"Q1", "Q2"} <= q.keys():
                q["Q3"] = _derive(year["M9"], [q["Q1"], q["Q2"]], "Q3")
        if "Q4" not in q and "FY" in year:
            if "M9" in year:
                q["Q4"] = _derive(year["FY"], [year["M9"]], "Q4")
            elif {"Q1", "Q2", "Q3"} <= q.keys():
                q["Q4"] = _derive(year["FY"], [q["Q1"], q["Q2"], q["Q3"]], "Q4")
    return [q[p] for p in ("Q1", "Q2", "Q3", "Q4") if p in q]


def _quarterly(facts: list[Fact]) -> list[Fact]:
    years: dict[tuple, dict[str, Fact]] = defaultdict(dict)
    quarters = []
    for fact in facts:
        if fact.fiscal_year is None:
            continue  # periods that couldn't be placed in the fiscal calendar
        if fact.period_start is None:  # balance-sheet item: the Q4 balance is the year-end one
            if fact.fiscal_period == "FY":
                fact = fact.model_copy(update={"fiscal_period": "Q4"})
            quarters.append(fact)
        else:
            year = years[(fact.canonical_name, fact.fiscal_year)]
            # two reported periods can share a label (rare); keep the later-ending one
            if (
                fact.fiscal_period not in year
                or fact.period_end > year[fact.fiscal_period].period_end
            ):
                year[fact.fiscal_period] = fact
    for year in years.values():
        quarters.extend(_quarters_for_flow(year))
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
    frequency="quarterly": standalone quarters Q1-Q4, deriving the ones not reported.
    """
    facts = get_reported_facts(conn, cik, canonical_names, as_of, mode)
    if frequency == "reported":
        return facts
    if frequency == "annual":
        return [f for f in facts if f.fiscal_period == "FY"]
    if frequency == "quarterly":
        return _quarterly(facts)
    raise ValueError(f"Unknown frequency: {frequency!r}")
