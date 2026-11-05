"""The grid sections of a backtest report (M10), from stored rows only.

Fixed in docs/designs/m10-more-dates.md before any result: the headline statistic is M8's (skill
and per-case d of the masked variant on all cases), but its test is read at the level of dates,
because the companies on one grid date share a news week and its macro surprise. The memory
test compares named and masked at h1 only, grouped by when the h1 outcome became public.
"""

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import numpy as np

from domains.evaluation import backtest as bt
from domains.evaluation import grid

BLOCK = 4  # consecutive dates per block in the moving-block sensitivity (Künsch 1989)
GROUPS = ("A", "B", "C")
GROUP_NAMES = {
    "A": "news and outcome before the cutoff",
    "B": "news before, outcome after",
    "C": "news and outcome after",
}


def case_date(case_id: str) -> date:
    return date.fromisoformat(case_id.rsplit("_", 1)[1])


# -- date-clustered inference -------------------------------------------------------------------


def date_means(ds: dict[str, float]) -> dict[date, float]:
    """The mean of d over the cases on each date, oldest date first."""
    by: dict[date, list[float]] = defaultdict(list)
    for case_id, d in ds.items():
        by[case_date(case_id)].append(d)
    return {k: statistics.fmean(v) for k, v in sorted(by.items())}


def _clusters(ds: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    by: dict[date, list[float]] = defaultdict(list)
    for case_id, d in ds.items():
        by[case_date(case_id)].append(d)
    keys = sorted(by)
    return (np.array([sum(by[k]) for k in keys], dtype=float),
            np.array([len(by[k]) for k in keys], dtype=float))  # fmt: skip


def _interval(means: np.ndarray, level: float) -> tuple[float, float]:
    tail = (1 - level) / 2 * 100
    lo, hi = np.percentile(means, [tail, 100 - tail])
    return float(lo), float(hi)


def date_bootstrap(
    ds: dict[str, float],
    level: float = 0.90,
    draws: int = bt.BOOTSTRAP_DRAWS,
    seed: int = bt.BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """Percentile interval for the mean d over cases, resampling whole dates with replacement."""
    sums, sizes = _clusters(ds)
    if not len(sums):
        return None
    rng = np.random.Generator(np.random.PCG64(seed))
    idx = rng.integers(0, len(sums), (draws, len(sums)))
    return _interval(sums[idx].sum(axis=1) / sizes[idx].sum(axis=1), level)


def block_bootstrap(
    ds: dict[str, float],
    block: int = BLOCK,
    level: float = 0.90,
    draws: int = bt.BOOTSTRAP_DRAWS,
    seed: int = bt.BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """Moving-block bootstrap over consecutive dates (neighbouring dates forecast overlapping
    quarters), blocks of `block`, for the mean d over cases."""
    sums, sizes = _clusters(ds)
    k = len(sums)
    if k == 0:
        return None
    b = min(block, k)
    per = math.ceil(k / b)
    rng = np.random.Generator(np.random.PCG64(seed))
    starts = rng.integers(0, k - b + 1, (draws, per))
    idx = (starts[:, :, None] + np.arange(b)[None, None, :]).reshape(draws, -1)[:, :k]
    return _interval(sums[idx].sum(axis=1) / sizes[idx].sum(axis=1), level)


@dataclass(frozen=True)
class DateTest:
    cases: int
    dates: int
    mean_d: float | None
    sign: bt.SignTest  # on per-date means
    interval: tuple[float, float] | None  # date bootstrap
    block: tuple[float, float] | None  # moving-block sensitivity

    @property
    def shown(self) -> bool:
        """The design's rule: date-level p < 0.05 and the date interval excludes zero."""
        return (
            self.sign.p is not None
            and self.sign.p < 0.05
            and self.interval is not None
            and (self.interval[1] < 0 or self.interval[0] > 0)
        )


def date_test(ds: dict[str, float]) -> DateTest:
    means = date_means(ds)
    return DateTest(
        cases=len(ds),
        dates=len(means),
        mean_d=statistics.fmean(ds.values()) if ds else None,
        sign=bt.sign_test(list(means.values())),
        interval=date_bootstrap(ds),
        block=block_bootstrap(ds),
    )


# -- the memory test ----------------------------------------------------------------------------


def memory_group(day: date, filed_at: str | None) -> str | None:
    """A, B or C for a case date and its h1 actual's filing date; None when unknown or when the
    news window overlaps the cutoff month (on neither grid)."""
    if filed_at is None:
        return None
    if grid.is_post_cutoff(day):
        return "C"
    if not grid.is_pre_cutoff(day):
        return None
    after = date.fromisoformat(filed_at) > grid.cutoff_month_end()
    return "B" if after else "A"


def h1_effects(rows: list[dict], variant: str) -> dict[tuple[str, str], tuple[float, dict]]:
    """(case, item) → (error with shocks − error without at h1, the baseline row), all cases
    (a case without shocks has 0, as in the headline)."""
    return {
        (p.case_id, p.item): (p.variant["error"] - p.baseline["error"], p.baseline)
        for p in bt.pairs(rows, variant)
        if p.horizon == 1
    }


def memory_gaps(rows: list[dict]) -> dict[str, dict[str, dict[str, float]]]:
    """item → group → {case: g}, g = e(named) − e(masked) at h1 (below 0: named helped more)."""
    named, masked = h1_effects(rows, "llm_named"), h1_effects(rows, "llm_masked")
    out: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for key in sorted(set(named) & set(masked)):
        case_id, item = key
        e_named, base = named[key]
        e_masked, _ = masked[key]
        group = memory_group(case_date(case_id), base.get("actual_filed_at"))
        if group is not None:
            out[item][group][case_id] = e_named - e_masked
    return out


# -- counts ---------------------------------------------------------------------------------------


def h1_closed(row: dict) -> bool:
    """The h1 quarter had already ended on the case date (a nowcast, not a forecast)."""
    return (
        row["period_end"] is not None and row["period_end"] < case_date(row["case_id"]).isoformat()
    )


@dataclass(frozen=True)
class Counts:
    cases: int
    scored: int
    not_yet_scorable: list[str]
    failed: dict[str, str]


def counts(case_ids: list[str], rows: list[dict], failures: dict[str, str]) -> Counts:
    """Every grid case lands in exactly one bucket: scored (an `ok` baseline row), failed, or not
    yet scorable (rows, but no actual reported yet)."""
    ok = {r["case_id"] for r in rows if r["variant"] == "baseline" and r["status"] == "ok"}
    waiting = sorted(c for c in case_ids if c not in ok and c not in failures)
    return Counts(len(case_ids), len(ok & set(case_ids)), waiting, dict(failures))


def quiet(rows: list[dict], events_chosen: dict[str, int], variant: str) -> dict[str, list[str]]:
    """Cases by what the AI did: 'shocks' (rows in the variant), 'no events' in the week, or
    'no shock' (events, but no material impact, or every proposal rejected)."""
    has = {r["case_id"] for r in rows if r["variant"] == variant}
    out: dict[str, list[str]] = {"shocks": [], "no events": [], "no shock": []}
    for case_id in sorted({r["case_id"] for r in rows}):
        if case_id in has:
            out["shocks"].append(case_id)
        elif events_chosen.get(case_id, 0) == 0:
            out["no events"].append(case_id)
        else:
            out["no shock"].append(case_id)
    return out
