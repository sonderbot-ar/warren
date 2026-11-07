"""A stored run's forecast against what was reported afterwards (backlog #128).

For each forecast quarter of a run, its revenue and EBIT next to the value as first reported in
the filings public by `actuals_on`, and the miss, scored as the M3 harness scores it. This is
hindsight by design: it reads filings dated after the run's as-of date, only to compare, and never
feeds a run. Gaps are coded (`Coded`, as in backlog #140), never raised, so a report or a screen
always gets an answer. Design: docs/designs/backlog-128-latest-day.md.
"""

import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from types import MappingProxyType

from domains.analysis.dcf import YEARS
from domains.analysis.math_engine import CHAINS, step_quarter
from domains.analysis.reported import Coded, Filing
from domains.analysis.reported import _Filings as Filings
from domains.analysis.runs import load_assumptions, load_outputs
from domains.evaluation.harness import (
    EvaluationError,
    _alternative,
    _quarterly,
    comparative,
    label,
    parse_label,
    score,
)
from domains.fundamentals.schemas import Fact

# a prior-year figure in the actual's filing that differs from the run's own by more than this
# means the filing recast the year (a disposal, a segment change): the miss is not shown
BASIS_TOLERANCE = 0.005
MISS_UNITS = {"revenue": "fraction_of_actual", "ebit": "fraction_of_actual_revenue"}
ITEMS = ("revenue", "ebit")


@dataclass(frozen=True)
class Item:
    name: str  # revenue or ebit
    unit: str | None  # the fact's unit, e.g. USD; values are raw, not in millions
    forecast: float
    actual: float | None
    miss: float | None  # |signed_miss|
    signed_miss: float | None  # (forecast − actual) ÷ scale; positive: the forecast was high
    miss_unit: str  # fraction_of_actual (revenue) or fraction_of_actual_revenue (EBIT)
    derived: bool = False
    filings: list[Filing] = field(default_factory=list)
    missing: Coded | None = None


@dataclass(frozen=True)
class Quarter:
    period: str  # the run's label, e.g. FY2019Q3
    fiscal_year: int
    fiscal_period: str
    horizon: int  # 1 for the run's first forecast quarter
    period_end: date | None  # None until the quarter is reported
    days: int | None
    items: list[Item]

    @property
    def reported(self) -> bool:
        return self.items[0].actual is not None


@dataclass(frozen=True)
class Hindsight:
    run_id: str
    ticker: str
    as_of: date
    actuals_on: date
    quarters: list[Quarter]

    def to_dict(self) -> dict:
        return _plain(asdict(self))


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _not_reported(period: str, actuals_on: date, item: str) -> Coded:
    return Coded(
        "not_reported",
        {"period": period, "item": item, "actuals_on": actuals_on.isoformat()},
        f"{item} for {period} was not yet in a 10-Q or 10-K by {actuals_on}",
    )


def _filings(facts: list[Fact], filings: Filings) -> list[Filing]:
    out, seen = [], set()
    for f in facts:
        for accession in f.inputs if f.derived else [f.accession_no]:
            if accession and accession not in seen:
                seen.add(accession)
                out.append(filings.get(accession))
    return out


def _gap(name: str, forecast: float, code: Coded, unit: str | None = None, **kw) -> Item:
    return Item(name, unit, forecast, kw.pop("actual", None), None, None, MISS_UNITS[name],
                missing=code, **kw)  # fmt: skip


def _basis_change(
    name: str,
    period: str,
    prior: str,
    expected: float | None,
    filing: float | None,
    inherited: bool,
) -> Coded | None:
    """`restated_basis` when the actual's own filing gives the year-earlier quarter a value other
    than the run's basis (beyond BASIS_TOLERANCE), or when that quarter's basis had changed."""
    params = {"period": period, "prior_period": prior, "run_value": expected,
              "filing_value": filing}  # fmt: skip
    if inherited:
        return Coded("restated_basis", params,
                     f"the basis of {name} changed at {prior}, so the gap for {period} is not a "
                     "forecast miss")  # fmt: skip
    if expected is None or filing is None or not expected:
        return None
    if abs(filing - expected) / abs(expected) <= BASIS_TOLERANCE:
        return None
    return Coded(
        "restated_basis",
        params,
        f"the filing that reported {period} gives {prior} {name} as {filing / 1e6:,.0f} million, "
        f"where the run had {expected / 1e6:,.0f} million: the basis changed (a restatement or "
        "another line), so the gap is not a forecast miss",
    )


class FactReads:
    """One company's filing reads, kept for several runs on one connection (backlog #252).

    `against_actuals` reads the same facts for every run of a company: the quarters as first
    reported by `actuals_on`, and the latest values as of each actual's filing date. Both depend
    only on the company, the date and the mode, never on the run, so a caller that scores many
    runs at once (`run_ranges.basis_flags`) passes one `FactReads` and each is read once. Keep
    one only while nothing is written to the facts: it never re-reads."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._facts: dict[tuple[str, date, str], Mapping[tuple, Fact]] = {}
        self._filings: dict[str, Filings] = {}

    def quarterly(self, cik: str, on: date, mode: str) -> Mapping[tuple, Fact]:
        """Read-only: one run can't change what the next run reads."""
        key = (cik, on, mode)
        if key not in self._facts:
            self._facts[key] = MappingProxyType(_quarterly(self.conn, cik, on, mode))
        return self._facts[key]

    def filings(self, cik: str) -> Filings:
        if cik not in self._filings:
            self._filings[cik] = Filings(self.conn, cik)
        return self._filings[cik]


def against_actuals(
    conn: sqlite3.Connection, run_id: str, actuals_on: date, reads: FactReads | None = None
) -> Hindsight:
    """Each forecast quarter of `run_id` against what was first reported by `actuals_on`.
    `reads`: shared filing reads when scoring many runs of one company (same answer, faster)."""
    run = conn.execute("SELECT ticker, cik, as_of FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise EvaluationError(f"run {run_id} is not stored")
    cik = run["cik"]
    reads = reads if reads is not None else FactReads(conn)
    outputs = load_outputs(conn, run_id)
    history = {(a.name, a.period): a for a in load_assumptions(conn, run_id)
               if a.name.startswith("history:")}  # fmt: skip
    periods = sorted(p for (n, p) in outputs if n == "revenue" and p not in YEARS)
    facts = reads.quarterly(cik, actuals_on, "first_reported")
    filings = reads.filings(cik)

    # what each prior-year figure should be on the run's basis: the run's own history rows, then
    # (for quarters 5-8, whose year-earlier quarter was itself forecast) that quarter's actual
    basis = {(a.name.removeprefix("history:"), p): a.value for (n, p), a in history.items()}
    changed: set[tuple[str, str]] = set()  # items whose basis already changed: so do later ones
    ebit_rows = sorted(p for (n, p) in history if n == "history:ebit")

    quarters = []
    for horizon, period in enumerate(periods, start=1):
        year, q = parse_label(period)
        prior = label(*step_quarter(year, q, -4))
        forecasts = {item: outputs[(item, period)] for item in ITEMS}
        revenue = facts.get(("revenue", year, f"Q{q}"))
        if revenue is None:
            items = [_gap(i, forecasts[i], _not_reported(period, actuals_on, i)) for i in ITEMS]
            quarters.append(Quarter(period, year, f"Q{q}", horizon, None, None, items))
            continue

        # the run's EBIT definition: its row a year earlier, else its newest history row
        known = history.get(("history:ebit", prior)) or (
            history[("history:ebit", ebit_rows[-1])] if ebit_rows else None
        )
        ebit_facts, ebit_gap, alternative = None, None, None
        if known is None:
            ebit_gap = Coded(
                "no_definition",
                {"period": period},
                f"the run has no EBIT history row, so its EBIT definition for {period} is unknown",
            )
        else:
            alternative = _alternative(known.method)
            chain = CHAINS["ebit"][alternative]
            chosen = [facts.get((n, year, f"Q{q}")) for n in chain]
            if all(chosen):
                ebit_facts = chosen
            else:
                others = [
                    " + ".join(alt)
                    for i, alt in enumerate(CHAINS["ebit"])
                    if i != alternative and all(facts.get((n, year, f"Q{q}")) for n in alt)
                ]
                ebit_gap = (
                    Coded(
                        "other_ebit_definition",
                        {"period": period, "definition": " + ".join(chain), "reported_as": others},
                        f"EBIT for {period} is reported only as {', '.join(others)}, not on the "
                        f"run's definition ({' + '.join(chain)})",
                    )
                    if others
                    else _not_reported(period, actuals_on, "ebit")
                )

        filed = max(f.filed_at for f in [revenue, *(ebit_facts or [])])
        comp = (
            comparative(reads.quarterly(cik, filed, "latest"), year, q, alternative)
            if alternative is not None
            else (None, None)
        )
        actuals = {"revenue": ([revenue], revenue.value)}
        if ebit_facts:
            actuals["ebit"] = (ebit_facts, sum(f.value for f in ebit_facts))
        items = []
        for idx, name in enumerate(ITEMS):
            if name not in actuals:
                items.append(_gap(name, forecasts[name], ebit_gap, revenue.unit))
                continue
            used, value = actuals[name]
            extra = {"actual": value, "derived": any(f.derived for f in used),
                     "filings": _filings(used, filings)}  # fmt: skip
            code = _basis_change(name, period, prior, basis.get((name, prior)), comp[idx],
                                 (name, prior) in changed)  # fmt: skip
            basis[(name, period)] = value
            if code is not None:
                changed.add((name, period))
                items.append(_gap(name, forecasts[name], code, revenue.unit, **extra))
                continue
            try:
                _, signed, _ = score(name, forecasts[name], value, revenue.value)
            except EvaluationError:
                code = Coded("zero_base", {"period": period},
                             f"{period}: the actual is zero, so the miss has no scale")  # fmt: skip
                items.append(_gap(name, forecasts[name], code, revenue.unit, **extra))
                continue
            extra.pop("actual")
            items.append(Item(name, revenue.unit, forecasts[name], value, abs(signed), signed,
                              MISS_UNITS[name], **extra))  # fmt: skip
        start = revenue.period_start
        days = (revenue.period_end - start).days + 1 if start else None
        quarters.append(Quarter(period, year, f"Q{q}", horizon, revenue.period_end, days, items))
    return Hindsight(run_id, run["ticker"], date.fromisoformat(run["as_of"]), actuals_on, quarters)
