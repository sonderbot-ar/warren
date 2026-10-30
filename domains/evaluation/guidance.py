"""Company guidance as shocks (M4 Step 4): transcribed figures in, shocks computed by code.

No agent picks a magnitude. The case librarian copies the old and new guided figures from the
dated release, with the exact sentence they come from; this module turns them into shocks with
one rule (docs/designs/m4-shock-model.md, "Conversion"):

1. Amounts first: a guided growth rate becomes an amount with the prior year's quarters as known
   on the case date; a guide over quarters partly reported already keeps only the unreported part.
2. The news is the revision: Δlevel = (new − old midpoint) / old midpoint on those amounts, the
   new range's ends giving low and high.
3. Quarters grow from the same quarter a year earlier, so the growth shock that moves a quarter's
   level by Δ is Δ × (1 + g) with g the run's growth for that quarter: one shock per quarter.
4. Margins: new guided margin − old guided margin, never the income change over revenue (that
   counts the revenue cut twice).
"""

import csv
import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from domains.analysis.dcf import QUARTERS
from domains.analysis.schemas import Assumption
from domains.analysis.shocks import Shock

GUIDANCE_PATH = Path(__file__).parent / "guidance.csv"
FIELDS = (
    "case_id guide_id item basis fiscal_year first_quarter last_quarter old_low old_high "
    "new_low new_high source_date accession quote"
).split()
OPTIONAL = ("unit",)  # blank means millions
SCALE = {"millions": 1e6, "billions": 1e9}
FIGURES = ("old_low", "old_high", "new_low", "new_high")


class GuidanceError(ValueError):
    """A guide can't be turned into shocks; the case fails with this reason."""


class Guide(BaseModel):
    case_id: str
    guide_id: str = Field(..., min_length=1)  # rows of one release share it
    item: Literal["revenue", "operating_income", "operating_margin"]
    basis: Literal["amount", "growth", "margin"]  # amount in `unit`; growth, margin in percent
    fiscal_year: int
    first_quarter: int = Field(..., ge=1, le=4)
    last_quarter: int = Field(..., ge=1, le=4)
    old_low: float
    old_high: float
    new_low: float
    new_high: float
    source_date: date
    accession: str = Field(..., pattern=r"^\d{10}-\d{2}-\d{6}$")
    quote: str = Field(..., min_length=1)
    unit: Literal["millions", "billions"] = "millions"  # amounts as the release prints them

    @model_validator(mode="after")
    def _valid(self) -> "Guide":
        if self.first_quarter > self.last_quarter:
            raise ValueError(f"{self.guide_id}: first_quarter after last_quarter")
        if self.old_low > self.old_high or self.new_low > self.new_high:
            raise ValueError(f"{self.guide_id}: a range's low is above its high")
        allowed = {"revenue": {"amount", "growth"}, "operating_income": {"amount"}}
        allowed["operating_margin"] = {"margin"}
        if self.basis not in allowed[self.item]:
            raise ValueError(f"{self.guide_id}: {self.item} can't be guided as {self.basis}")
        if self.unit != "millions" and self.basis != "amount":
            raise ValueError(f"{self.guide_id}: only amounts take a unit")
        return self

    @property
    def quarters(self) -> list[str]:
        return [
            f"FY{self.fiscal_year}Q{q}" for q in range(self.first_quarter, self.last_quarter + 1)
        ]


def _numbers(text: str) -> set[float]:
    return {float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))}


def load_guides(path: Path = GUIDANCE_PATH) -> list[Guide]:
    """Every row validated; every figure must be readable in its quote, so a typo fails."""
    out = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if set(FIELDS) - set(reader.fieldnames or []):
            raise GuidanceError(f"{path.name}: missing columns")
        for line, row in enumerate(reader, start=2):
            values = {k: (row[k] or "").strip() for k in FIELDS}
            values |= {k: row[k].strip() for k in OPTIONAL if (row.get(k) or "").strip()}
            try:
                guide = Guide(**values)
            except ValueError as e:
                raise GuidanceError(f"{path.name} line {line}: {e}") from e
            found = _numbers(guide.quote)
            missing = [f for f in FIGURES if abs(getattr(guide, f)) not in {abs(n) for n in found}]
            if missing:
                raise GuidanceError(f"{path.name} line {line}: {missing} not in the quote")
            out.append(guide)
    return out


def guidance_sha256(path: Path = GUIDANCE_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guard_source_dates(guides: list[Guide], case_date: date) -> None:
    """A guide made public after the case date is look-ahead: the case fails."""
    late = [g.guide_id for g in guides if g.source_date > case_date]
    if late:
        raise GuidanceError(f"guidance dated after the case date {case_date}: {late}")


def _mid(low: float, high: float) -> float:
    return (low + high) / 2


def _index(rows: list[Assumption]) -> dict[tuple[str, str], float]:
    return {(a.name, a.period): a.value for a in rows}


def to_shocks(guides: list[Guide], rows: list[Assumption]) -> list[Shock]:
    """The shocks a case's guidance implies for its baseline run (the run's own rows)."""
    index = _index(rows)
    forecast = sorted(p for (n, p) in index if n == "revenue_growth" and "Q" in p)[:QUARTERS]
    position = {p: h for h, p in enumerate(forecast, start=1)}

    def actual(quarter: str) -> float:
        for name in ("revenue_seed", "history:revenue"):
            if (name, quarter) in index:
                return index[(name, quarter)]
        raise GuidanceError(f"revenue for {quarter} is not known on the case date")

    def open_quarters(guide: Guide) -> tuple[list[str], float]:
        """(unreported guided quarters, revenue already reported in the guided span)"""
        unreported = [q for q in guide.quarters if q in position]
        reported = [q for q in guide.quarters if q not in position]
        if not unreported:
            raise GuidanceError(f"{guide.guide_id}: every guided quarter is already reported")
        if forecast and reported and max(reported) > forecast[0]:
            raise GuidanceError(f"{guide.guide_id}: guided quarters past the forecast grid")
        return unreported, sum(actual(q) for q in reported)

    by_release: dict[str, dict[str, Guide]] = {}
    for g in guides:
        if g.item in by_release.setdefault(g.guide_id, {}):
            raise GuidanceError(f"{g.guide_id}: two {g.item} rows")
        by_release[g.guide_id][g.item] = g

    shocks = []
    for guide_id, items in by_release.items():
        revenue = items.get("revenue")
        if revenue is not None:
            unreported, done = open_quarters(revenue)
            if revenue.basis == "growth":
                prior = sum(
                    actual(f"FY{revenue.fiscal_year - 1}Q{q[-1]}") for q in revenue.quarters
                )
                amounts = {f: prior * (1 + getattr(revenue, f) / 100) for f in FIGURES}
            else:
                amounts = {f: getattr(revenue, f) * SCALE[revenue.unit] for f in FIGURES}
            old = _mid(amounts["old_low"], amounts["old_high"]) - done
            if old <= 0:
                raise GuidanceError(f"{guide_id}: guided revenue left for open quarters is ≤ 0")
            new_mid = _mid(amounts["new_low"], amounts["new_high"]) - done
            levels = [
                (amounts["new_low"] - done) / old - 1,
                new_mid / old - 1,
                (amounts["new_high"] - done) / old - 1,
            ]
            for quarter in unreported:
                g = index[("revenue_growth", quarter)]
                low, base, high = (100 * level * (1 + g) for level in levels)
                shocks.append(
                    _shock(
                        f"{guide_id}:revenue:{quarter}",
                        "revenue_growth",
                        (low, base, high),
                        position[quarter],
                        revenue,
                    )
                )

        margin = items.get("operating_margin")
        income = items.get("operating_income")
        if margin is not None and income is not None:
            raise GuidanceError(f"{guide_id}: both a margin and an income guide")
        if income is not None:
            if (
                revenue is None
                or revenue.basis != "amount"
                or revenue.quarters != income.quarters
                or revenue.unit != income.unit
            ):
                raise GuidanceError(
                    f"{guide_id}: operating income needs revenue guided in amounts for the same "
                    "quarters, in the same unit, in the same release"
                )
            old_margin = _mid(income.old_low, income.old_high) / _mid(
                revenue.old_low, revenue.old_high
            )
            revenue_mid = _mid(revenue.new_low, revenue.new_high)
            new = [
                income.new_low / revenue_mid,
                _mid(income.new_low, income.new_high) / revenue_mid,
                income.new_high / revenue_mid,
            ]
            margin_points = [100 * (m - old_margin) for m in new]
            margin = income
        elif margin is not None:
            old_margin = _mid(margin.old_low, margin.old_high)
            margin_points = [
                margin.new_low - old_margin,
                _mid(margin.new_low, margin.new_high) - old_margin,
                margin.new_high - old_margin,
            ]
        if margin is not None:
            unreported, _ = open_quarters(margin)
            if len(unreported) != len(margin.quarters):
                raise GuidanceError(
                    f"{guide_id}: a margin guide over quarters already partly reported is not used"
                )
            for quarter in unreported:
                shocks.append(
                    _shock(
                        f"{guide_id}:margin:{quarter}",
                        "operating_margin",
                        tuple(margin_points),
                        position[quarter],
                        margin,
                    )
                )
    return shocks


def _shock(shock_id: str, driver: str, values: tuple, start: int, guide: Guide) -> Shock:
    low, base, high = sorted(values)  # the new range's ends, whichever way the revision went
    return Shock(
        shock_id=shock_id,
        driver=driver,
        low=low,
        base=base,
        high=high,
        start_period=start,
        horizon=1,
        decay=1.0,
        source="computed",
        rationale=f"{guide.accession} ({guide.source_date}): {guide.quote}",
    )
