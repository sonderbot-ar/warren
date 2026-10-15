from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

FiscalPeriod = Literal["Q1", "Q2", "Q3", "Q4", "H1", "M9", "FY"]


class Fact(BaseModel):
    """One canonical value for one period, as it was known on the query's as-of date."""

    canonical_name: str = Field(..., description="Warren's name, e.g. 'revenue'")
    xbrl_concept: str = Field(
        ..., description="Tag the value came from; for derived, the tags used"
    )
    period_start: date | None = Field(default=None, description="None for balance-sheet items")
    period_end: date
    fiscal_year: int | None = None
    fiscal_period: FiscalPeriod | None = None
    value: float
    unit: str
    accession_no: str | None = Field(default=None, description="Filing id; None when derived")
    filed_at: date = Field(..., description="When it became public; for derived, the latest input")
    restated: bool = Field(default=False, description="Differs from the first-reported value")
    derived: bool = Field(default=False, description="Computed by Warren, not reported")
    inputs: list[str] = Field(default_factory=list, description="Accessions a derived value used")
    mixed_vintage: bool = Field(
        default=False, description="Derived from a mix of restated and first-reported inputs"
    )
