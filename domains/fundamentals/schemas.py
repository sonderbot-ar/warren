from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

FiscalPeriod = Literal["Q1", "Q2", "Q3", "Q4", "H1", "M9", "FY"]


class OwnTagCheck(BaseModel):
    """Why a quarter its filing gave only under a lower-ranked tag was kept on that tag instead of
    moving to its year's (backlog #336): the same subtraction on the quarter's own tag did not
    come within `RECAST_MOVE` of the quarter (backlog #329)."""

    year_tag: str = Field(..., description="The one tag of the year and the periods before it")
    on_year_tag: float = Field(..., description="The quarter derived on the year's tag")
    on_own_tag: float = Field(
        ..., description="The same derivation on the quarter's own tag, from the inputs' filings"
    )
    inputs: list[str] = Field(
        default_factory=list, description="Accessions of the own-tag inputs, minuend first"
    )


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
    one_basis: bool = Field(
        default=False,
        description="Derived from inputs on one basis instead of the newest ones (backlog #264)",
    )
    narrower_tag: str | None = Field(
        default=None,
        description=(
            "A derived quarter that replaced the quarter as reported, because that filing gave it "
            "only under this tag, ranked below the one tag of the year and the periods before it "
            "(backlog #324)"
        ),
    )
    kept_on_own_tag: OwnTagCheck | None = Field(
        default=None,
        description=(
            "A reported quarter under a lower-ranked tag than its year's, kept as reported because "
            "its own tag disagrees with its year (backlog #329, #336); otherwise None"
        ),
    )
