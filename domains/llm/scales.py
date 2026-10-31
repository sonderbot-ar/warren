"""From the model's classes to a shock's numbers (M6 Step B). Pure functions: no I/O but the table.

The model picks a driver, a direction, a size class, a duration class and a start quarter. Code
scales the size by σ, the robust spread of the driver's four-quarter change in the company's own
reported history (the median absolute deviation × 1.4826), and builds an M4 shock. A shock that
would push the driver somewhere the company has never been is scaled down and flagged.

Units: percentage points, basis points for the risk premium, as in M4. Every multiple and bound
lives in `scales.csv`: judgments, stated as such, not a calibration.
"""

import csv
import statistics
from dataclasses import dataclass
from pathlib import Path

from domains.analysis import shocks as m4
from domains.analysis.dcf import Inputs

SCALES_PATH = Path(__file__).parent / "scales.csv"
MAD_TO_SD = 1.4826  # the median absolute deviation of normal data, scaled to its σ
Z99_OVER_Z90 = 2.3263478740408408 / 1.2815515655446004  # the 1st and 99th percentile reach
DURATIONS = {"one_quarter": (1, 1.0), "fading": (8, 0.7), "lasting": (8, 1.0)}  # (horizon, decay)
GRID = m4.GRID_QUARTERS
ROW = {"revenue_growth": "revenue_growth", "operating_margin": "operating_margin",
       "capex_intensity": "capex_pct"}  # fmt: skip


def load_scales(path: Path = SCALES_PATH) -> dict[str, float]:
    with open(path, newline="", encoding="utf-8") as f:
        lines = [line for line in f if not line.startswith("#")]
    return {r["key"]: float(r["value"]) for r in csv.DictReader(lines)}


def four_quarter_changes(series: list[float]) -> list[float]:
    """d_q = x_q − x_{q−4}, in order."""
    return [b - a for a, b in zip(series, series[4:], strict=False)]


def mad_sigma(values: list[float]) -> float:
    centre = statistics.median(values)
    return MAD_TO_SD * statistics.median(abs(v - centre) for v in values)


@dataclass(frozen=True)
class Sigma:
    value: float  # points (basis points for the risk premium)
    flag: str | None  # fallback | floored | capped
    changes: list[float]  # the four-quarter changes it came from, in points


def sigma(driver: str, series: list[float], scales: dict[str, float]) -> Sigma:
    """σ from a driver's quarterly series (fractions, oldest first): the last 12 changes."""
    if driver == "risk_premium":
        return Sigma(scales["risk_premium_sigma"], None, [])
    n = int(scales["min_changes"])
    changes = [100 * d for d in four_quarter_changes(series)][-n:]
    if len(changes) < n:
        return Sigma(scales[f"{driver}_fallback"], "fallback", changes)
    value, flag = mad_sigma(changes), None
    floor, cap = scales[f"{driver}_floor"], scales[f"{driver}_cap"]
    if value < floor:
        value, flag = floor, "floored"
    elif value > cap:
        value, flag = cap, "capped"
    return Sigma(value, flag, changes)


def magnitudes(
    direction: str, size: str, s: float, scales: dict, driver: str = ""
) -> tuple[float, float, float]:
    """(low, base, high): base = ± multiple × σ (the risk premium: fixed basis points), and a
    range of the same width for every size."""
    step = (
        scales[f"risk_premium_{size}"]
        if driver == "risk_premium"
        else scales[f"multiple_{size}"] * s
    )
    base = (1 if direction == "up" else -1) * step
    width = scales["range_width"] * s
    return base - width, base, base + width


def timing(duration: str, start: int) -> tuple[int, float]:
    """(horizon, decay); permanent runs to quarter 20, so it is in force in Y5 and the terminal."""
    if duration == "permanent":
        return GRID + 1 - start, 1.0
    return DURATIONS[duration]


@dataclass(frozen=True)
class Bounds:
    """Where a driver may go: (low, high) in the driver's own units, per forecast period."""

    capex_floor: float = 0.0
    margin: tuple[float, float] | None = None  # fractions
    level_band: float = 0.5  # revenue level within 1 ± this


def margin_bounds(margins: list[float], s: Sigma, scales: dict) -> tuple[float, float]:
    """The last 12 quarters' lowest and highest margin, widened by a multiple of σ (points)."""
    recent = margins[-int(scales["min_changes"]) :]
    widen = scales["margin_band_sigmas"] * s.value / 100
    return min(recent) - widen, max(recent) + widen


def _limit(path: float, delta: float, low: float | None, high: float | None) -> float:
    """The largest share f in [0, 1] of `delta` that keeps path + f × delta within the bounds."""
    f = 1.0
    if delta < 0 and low is not None and path + delta < low:
        f = max(0.0, (low - path) / delta) if path > low else 0.0
    if delta > 0 and high is not None and path + delta > high:
        f = min(f, max(0.0, (high - path) / delta) if path < high else 0.0)
    return f


def clip_factor(
    driver: str, low: float, base: float, high: float, effects: list[float], inp: Inputs,
    bounds: Bounds,
) -> float:  # fmt: skip
    """How much to scale (low, base, high) so the 1st and 99th percentiles stay in bounds."""
    if driver == "risk_premium":
        return 1.0
    reach = (base - Z99_OVER_Z90 * (base - low), base + Z99_OVER_Z90 * (high - base))
    factor = 1.0
    for i, share in enumerate(effects):
        if not share:
            continue
        for extreme in reach:
            delta = extreme * m4.UNIT[driver] * share
            if driver == "revenue_growth":  # a level shock: the multiplier stays in the band
                factor = min(factor, _limit(1.0, delta, 1 - bounds.level_band,
                                            1 + bounds.level_band))  # fmt: skip
            elif driver == "capex_intensity":
                factor = min(factor, _limit(inp.driver["capex_pct"][i], delta,
                                            bounds.capex_floor, None))  # fmt: skip
            elif bounds.margin is not None:
                factor = min(factor, _limit(inp.driver["operating_margin"][i], delta,
                                            *bounds.margin))  # fmt: skip
    return factor


@dataclass(frozen=True)
class Sized:
    low: float
    base: float
    high: float
    horizon: int
    decay: float
    clipped: bool

    def shock(self, shock_id: str, driver: str, start: int, event_id: str | None,
              rationale: str) -> m4.Shock:  # fmt: skip
        return m4.Shock(
            shock_id=shock_id, event_id=event_id, driver=driver, low=self.low, base=self.base,
            high=self.high, start_period=start, horizon=self.horizon, decay=self.decay,
            source="llm_proposed", rationale=rationale,
            basis="level" if driver == "revenue_growth" else "growth",
        )  # fmt: skip


def size_shock(
    driver: str, direction: str, size: str, duration: str, start: int, s: Sigma, inp: Inputs,
    bounds: Bounds, scales: dict,
) -> Sized:  # fmt: skip
    """The numbers of one proposed shock, clipped to the bounds when needed."""
    low, base, high = magnitudes(direction, size, s.value, scales, driver)
    horizon, decay = timing(duration, start)
    probe = m4.Shock(shock_id="probe", driver=driver, low=low, base=base, high=high,
                     start_period=start, horizon=horizon, decay=decay, source="llm_proposed",
                     rationale="probe")  # fmt: skip
    factor = clip_factor(driver, low, base, high, m4.period_effects(probe), inp, bounds)
    return Sized(low * factor, base * factor, high * factor, horizon, decay, factor < 1.0)
