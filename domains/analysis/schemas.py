from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["computed", "user", "llm_proposed"]
SINGLE = "-"  # the period of an assumption with one value for the whole run


class Assumption(BaseModel):
    """One input to a DCF run: a value, where it came from and how it was produced."""

    name: str
    period: str = Field(..., description="Forecast period label, or '-' for a single value")
    value: float | None = Field(..., description="None only for a user's choice of method")
    source: Source
    method: str = Field(..., min_length=1, description="The rule, tags and filings behind it")
