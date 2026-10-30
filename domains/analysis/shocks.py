"""Shocks: time-shaped changes to a run's drivers (M4, Decision 6).

A shock moves one driver by a magnitude for a while. Its shape is computed on a 20-quarter grid,
h = 1…20: the run's 8 forecast quarters map one to one, and each of Y3, Y4 and Y5 takes the mean
of its four quarters' effects. Magnitudes are in percentage points (basis points for the risk
premium); positive means a higher driver. The magnitude may be a number or a numpy array of
samples: applying a shock is the same arithmetic either way.
"""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from domains.analysis import financial_math as fm
from domains.analysis.dcf import QUARTERS, YEARS, Inputs

GRID_QUARTERS = QUARTERS + 4 * len(YEARS)  # 20
Driver = Literal["revenue_growth", "operating_margin", "capex_intensity", "risk_premium"]
DRIVER_ROWS = {
    "revenue_growth": "revenue_growth",
    "operating_margin": "operating_margin",
    "capex_intensity": "capex_pct",
}
UNIT = {"revenue_growth": 0.01, "operating_margin": 0.01, "capex_intensity": 0.01}
UNIT["risk_premium"] = 0.0001  # basis points


class Shock(BaseModel):
    shock_id: str = Field(..., min_length=1)
    event_id: str | None = None  # None for a manual shock
    driver: Driver
    low: float
    base: float
    high: float
    start_period: int = Field(..., description="first affected forecast quarter, 1 = the first")
    horizon: int = Field(..., description="quarters the shock can last")
    decay: float = Field(..., description="share of the effect left each quarter, in (0, 1]")
    source: Literal["user", "computed", "llm_proposed"]
    rationale: str = Field(..., min_length=1, description="evidence: a URL or accession number")

    @model_validator(mode="after")
    def _valid(self) -> "Shock":
        if not self.low <= self.base <= self.high:
            raise ValueError(f"{self.shock_id}: need low ≤ base ≤ high")
        try:
            fm.shock_shape(self.start_period, self.horizon, self.decay, GRID_QUARTERS)
        except fm.FinancialMathError as e:
            raise ValueError(f"{self.shock_id}: {e}") from e
        return self


def period_effects(shock: Shock) -> list[float]:
    """Share of the magnitude in force in each forecast period (8 quarters, then Y3–Y5)."""
    shape = fm.shock_shape(shock.start_period, shock.horizon, shock.decay, GRID_QUARTERS)
    years = [shape[i : i + 4] for i in range(QUARTERS, GRID_QUARTERS, 4)]
    return shape[:QUARTERS] + [sum(year) / 4 for year in years]


def apply(inp: Inputs, shocks: list[Shock], magnitudes: list | None = None) -> Inputs:
    """The run's inputs with the shocks added; magnitudes default to each shock's base."""
    if magnitudes is None:
        magnitudes = [s.base for s in shocks]
    if len(magnitudes) != len(shocks):
        raise ValueError("one magnitude per shock")
    driver = {name: list(path) for name, path in inp.driver.items()}
    shift = list(inp.cost_of_equity_shift or [0.0] * len(inp.periods))
    for shock, magnitude in zip(shocks, magnitudes, strict=True):
        size = magnitude * UNIT[shock.driver]
        path = shift if shock.driver == "risk_premium" else driver[DRIVER_ROWS[shock.driver]]
        for i, share in enumerate(period_effects(shock)):
            if share:
                path[i] = path[i] + size * share
    has_shift = inp.cost_of_equity_shift is not None or any(
        s.driver == "risk_premium" for s in shocks
    )
    return inp.replace(driver=driver, cost_of_equity_shift=shift if has_shift else None)


def shocks_sha256(shocks: list[Shock]) -> str:
    """Hash of the shocks' fields, in order, so an edited shock can't pass as the one simulated."""
    payload = json.dumps([s.model_dump() for s in shocks], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
