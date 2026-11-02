"""The M8 backtest metrics: does news make the forecast better? Pure functions on stored rows.

Rows are `eval_results` rows as dicts. Every statistic is computed per item (revenue, EBIT) and
per variant; named and masked never borrow each other's rows. Design and review:
docs/designs/m8-backtest.md (Metrics).

- Populations. `all` (the headline): every scored quarter of every case; where the variant has
  no row (the AI proposed nothing that applies), its forecast is the baseline's. `moved`: only
  the case-items whose p50 differs from the baseline in some scored quarter. `no_scope`: `all`
  without the cases whose horizon holds a deal closing (`scope_change`). `with_shocks` (company
  guidance) is only ever judged on its own cases.
- The unit of evidence for tests is the case: a case's quarters share one run and one set of
  shocks, so they are not independent.
"""

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

CENT = 0.005  # a p50 within half a cent of the baseline has not moved
BOOTSTRAP_SEED = 20261102
BOOTSTRAP_DRAWS = 10_000
ALPHA = 0.2  # p10-p90 is the central 80% interval
Z95 = 1.959963984540054
POPULATIONS = ("all", "moved", "no_scope")


@dataclass(frozen=True)
class Pair:
    """One scored quarter: the baseline row and the variant's row (the baseline's if none)."""

    case_id: str
    item: str
    horizon: int
    baseline: dict
    variant: dict
    filled: bool  # the variant had no row here, so it takes the baseline's forecast


def _key(r: dict) -> tuple:
    return (r["case_id"], r["item"], r["period"])


def moved(rows: list[dict], variant: str) -> set[tuple[str, str]]:
    """(case, item) pairs where some quarter's p50 differs from the baseline by over half a cent."""
    base = {_key(r): r["forecast"] for r in rows if r["variant"] == "baseline"}
    return {
        (r["case_id"], r["item"])
        for r in rows
        if r["variant"] == variant and abs(r["forecast"] - base[_key(r)]) > CENT
    }


def pairs(
    rows: list[dict], variant: str, population: str = "all", scope_cases: set[str] = frozenset()
) -> list[Pair]:
    """Matched scored quarters of `variant` against the baseline, for one population."""
    if population not in POPULATIONS:
        raise ValueError(f"unknown population {population!r}")
    own = {_key(r): r for r in rows if r["variant"] == variant and r["status"] == "ok"}
    has_rows = {r["case_id"] for r in rows if r["variant"] == variant}
    keep = moved(rows, variant) if population == "moved" else None
    out = []
    for b in rows:
        if b["variant"] != "baseline" or b["status"] != "ok":
            continue
        if variant == "with_shocks" and b["case_id"] not in has_rows:
            continue  # guidance exists for a few cases only; never filled
        if keep is not None and (b["case_id"], b["item"]) not in keep:
            continue
        if population == "no_scope" and b["case_id"] in scope_cases:
            continue
        v = own.get(_key(b))
        out.append(Pair(b["case_id"], b["item"], b["horizon"], b, v or b, v is None))
    return out


def by_item(ps: list[Pair]) -> dict[str, list[Pair]]:
    out: dict[str, list[Pair]] = defaultdict(list)
    for p in ps:
        out[p.item].append(p)
    return dict(out)


# -- skill and the paired test -----------------------------------------------------------------


def skill(ps: list[Pair]) -> tuple[float, float] | None:
    """(mean skill, median skill) of the variant against the baseline on the same quarters.

    SS = 1 − mean error / mean reference error (Murphy 1988, applied to Warren's errors); the
    median version uses medians. Above 0 is better than the reference. None without quarters
    or when the baseline has no error at all."""
    if not ps:
        return None
    ref = [p.baseline["error"] for p in ps]
    var = [p.variant["error"] for p in ps]
    mean_ref, median_ref = statistics.fmean(ref), statistics.median(ref)
    if mean_ref == 0 or median_ref == 0:
        return None
    return 1 - statistics.fmean(var) / mean_ref, 1 - statistics.median(var) / median_ref


def skill_against(variant_ps: list[Pair], reference_rows: dict[tuple, dict]) -> float | None:
    """Mean skill of the variant against another variant (e.g. naive_srw) on matched quarters."""
    matched = [(p, reference_rows.get(_key(p.baseline))) for p in variant_ps]
    matched = [(p, r) for p, r in matched if r is not None and r["status"] == "ok"]
    if not matched:
        return None
    ref = statistics.fmean(r["error"] for _, r in matched)
    return None if ref == 0 else 1 - statistics.fmean(p.variant["error"] for p, _ in matched) / ref


def case_differences(ps: list[Pair]) -> dict[str, float]:
    """d per case: mean error of the variant minus mean error of the baseline, over its quarters.
    Below 0, the variant was better on that case."""
    errors: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for p in ps:
        errors[p.case_id].append((p.variant["error"], p.baseline["error"]))
    return {
        case: statistics.fmean(v for v, _ in e) - statistics.fmean(b for _, b in e)
        for case, e in errors.items()
    }


@dataclass(frozen=True)
class SignTest:
    better: int  # cases where the variant's error was lower (d < 0)
    worse: int
    ties: int  # d exactly 0: left out of the test
    p: float | None  # exact two-sided; None when no case differs


def sign_test(ds: list[float]) -> SignTest:
    """Exact two-sided sign test on the non-zero differences, p = ½ under no difference."""
    better = sum(d < 0 for d in ds)
    worse = sum(d > 0 for d in ds)
    n = better + worse
    if n == 0:
        return SignTest(better, worse, len(ds), None)
    k = min(better, worse)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return SignTest(better, worse, len(ds) - n, min(1.0, 2 * tail))


def bootstrap_mean(
    ds: list[float], level: float = 0.90, draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED
) -> tuple[float, float] | None:
    """Percentile interval for the mean of d, resampling cases with replacement (fixed seed)."""
    if not ds:
        return None
    rng = np.random.Generator(np.random.PCG64(seed))
    values = np.asarray(ds, dtype=float)
    picks = rng.integers(0, len(values), size=(draws, len(values)))
    means = values[picks].mean(axis=1)
    tail = (1 - level) / 2 * 100
    lo, hi = np.percentile(means, [tail, 100 - tail])
    return float(lo), float(hi)


def by_horizon(ps: list[Pair]) -> dict[int, tuple[float, int]]:
    """Mean of (variant error − baseline error) by horizon, with the number of quarters."""
    diffs: dict[int, list[float]] = defaultdict(list)
    for p in ps:
        diffs[p.horizon].append(p.variant["error"] - p.baseline["error"])
    return {h: (statistics.fmean(d), len(d)) for h, d in sorted(diffs.items())}


# -- direction ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Direction:
    hits: int
    n: int  # quarters with both directions known
    unknown: int  # scored quarters whose actual (or forecast) direction is unknown
    rose: int  # of the n, actual quarters that rose: the score of "always up"

    @property
    def rate(self) -> float | None:
        return self.hits / self.n if self.n else None

    @property
    def base_rate(self) -> float | None:
        return self.rose / self.n if self.n else None


def direction(rows: list[dict]) -> Direction:
    """Hit rate of up/flat/down (harness.direction, ±0.5% of the prior year is flat)."""
    known = [r for r in rows if r["direction_actual"] is not None and r["direction_forecast"]
             is not None]  # fmt: skip
    return Direction(
        hits=sum(r["direction_forecast"] == r["direction_actual"] for r in known),
        n=len(known),
        unknown=len(rows) - len(known),
        rose=sum(r["direction_actual"] == 1 for r in known),
    )


# -- the band ----------------------------------------------------------------------------------


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for a share k / n (Wilson 1927)."""
    if n == 0:
        return None
    share = k / n
    centre = (share + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(share * (1 - share) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


@dataclass(frozen=True)
class Coverage:
    inside: int
    n: int

    @property
    def share(self) -> float | None:
        return self.inside / self.n if self.n else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.inside, self.n)


def coverage(rows: list[dict]) -> Coverage:
    """Actuals with p10 ≤ actual ≤ p90 (the ends count as inside), on scored banded rows."""
    banded = [r for r in rows if r["status"] == "ok" and r["p10"] is not None]
    return Coverage(sum(r["p10"] <= r["actual"] <= r["p90"] for r in banded), len(banded))


def is_wide(row: dict) -> bool:
    """A shock moved this quarter's band: p90 above p10 by over half a cent."""
    return row["p10"] is not None and row["p90"] - row["p10"] > CENT


def interval_score(low: float, high: float, actual: float, scale: float, alpha: float = ALPHA):
    """Gneiting & Raftery (2007) eq. 43, lower is better, divided by `scale` (actual revenue).

    The width, plus 2/α times any miss. A point forecast is an interval of width 0."""
    if scale == 0:
        raise ValueError("cannot scale an interval score by a zero revenue")
    miss_low = max(low - actual, 0.0)
    miss_high = max(actual - high, 0.0)
    return ((high - low) + (2 / alpha) * (miss_low + miss_high)) / abs(scale)


def interval_scores(ps: list[Pair]) -> tuple[float, float, int] | None:
    """Mean interval score of the variant's band and of the baseline's point, on the quarters
    where the variant's band is wide; (variant, baseline, quarters)."""
    wide = [p for p in ps if not p.filled and is_wide(p.variant)]
    if not wide:
        return None
    var = [interval_score(p.variant["p10"], p.variant["p90"], p.variant["actual"],
                          p.variant["actual_revenue"]) for p in wide]  # fmt: skip
    base = [interval_score(p.baseline["forecast"], p.baseline["forecast"], p.baseline["actual"],
                           p.baseline["actual_revenue"]) for p in wide]  # fmt: skip
    return statistics.fmean(var), statistics.fmean(base), len(wide)


# -- named against masked ----------------------------------------------------------------------


def opposite_moves(rows: list[dict]) -> list[tuple[str, str]]:
    """(case, item) where named and masked move the item in opposite directions: the sign of the
    sum over quarters of p50 − baseline differs, both non-zero."""
    base = {_key(r): r["forecast"] for r in rows if r["variant"] == "baseline"}
    total: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r["variant"] in ("llm_named", "llm_masked"):
            total[(r["case_id"], r["item"])][r["variant"]] += r["forecast"] - base[_key(r)]
    out = []
    for key, t in sorted(total.items()):
        named, masked = t.get("llm_named", 0.0), t.get("llm_masked", 0.0)
        if abs(named) > CENT and abs(masked) > CENT and (named > 0) != (masked > 0):
            out.append(key)
    return out
