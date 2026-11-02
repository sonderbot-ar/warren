"""M9 range metrics and report: does about 80% of the actuals fall inside the p10–p90 range?

Pure functions on `range_results` rows (as dicts), then a Markdown report. The pass rule, the
clusters and the bootstrap seed are fixed in docs/designs/m9-honest-ranges.md before any result.
"""

import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import numpy as np

from domains.evaluation.backtest import BOOTSTRAP_DRAWS, BOOTSTRAP_SEED, interval_score, wilson
from domains.evaluation.ranges import POOLS, ROLLING_FROM

TARGET = 0.80
POINT_BAND = (0.70, 0.90)  # "met on average" needs coverage inside this band
COMPANY_BAND = (0.65, 0.95)  # "met for every company" needs each company inside this one
BLOCK = 4  # calendar quarters per block in the moving-block sensitivity
ITEMS = ("revenue", "ebit")


def calendar_quarter(period_end: str) -> tuple[int, int]:
    """The calendar quarter a fiscal quarter ends in: WMT's 2020-04-30 is (2020, 2)."""
    d = date.fromisoformat(period_end)
    return d.year, (d.month - 1) // 3 + 1


def scored(rows: list[dict]) -> list[dict]:
    """Rows with a range and a reported actual."""
    return [r for r in rows if r["status"] == "ok"]


def is_inside(r: dict) -> bool:
    return r["p10"] <= r["actual"] <= r["p90"]


@dataclass(frozen=True)
class Cover:
    inside: int
    below: int
    above: int

    @property
    def n(self) -> int:
        return self.inside + self.below + self.above

    @property
    def share(self) -> float | None:
        return self.inside / self.n if self.n else None

    @property
    def wilson(self) -> tuple[float, float] | None:
        return wilson(self.inside, self.n)


def cover(rows: list[dict]) -> Cover:
    """Inside (ends count as inside, as M8), below p10 and above p90, on scored rows."""
    rs = scored(rows)
    below = sum(r["actual"] < r["p10"] for r in rs)
    above = sum(r["actual"] > r["p90"] for r in rs)
    return Cover(len(rs) - below - above, below, above)


def _clusters(rows: list[dict]) -> dict[tuple[int, int], list[bool]]:
    out: dict[tuple[int, int], list[bool]] = defaultdict(list)
    for r in scored(rows):
        out[calendar_quarter(r["period_end"])].append(is_inside(r))
    return dict(sorted(out.items()))


def _interval(shares: np.ndarray) -> tuple[float, float]:
    lo, hi = np.percentile(shares, [5, 95])
    return float(lo), float(hi)


def cluster_bootstrap(
    rows: list[dict], draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED
) -> tuple[float, float] | None:
    """90% percentile interval of coverage, resampling calendar quarters with replacement."""
    clusters = list(_clusters(rows).values())
    if not clusters:
        return None
    inside = np.array([sum(c) for c in clusters], dtype=float)
    size = np.array([len(c) for c in clusters], dtype=float)
    rng = np.random.Generator(np.random.PCG64(seed))
    idx = rng.integers(0, len(clusters), (draws, len(clusters)))
    return _interval(inside[idx].sum(axis=1) / size[idx].sum(axis=1))


def block_bootstrap(
    rows: list[dict], block: int = BLOCK, draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED
) -> tuple[float, float] | None:
    """Moving-block bootstrap (Künsch 1989) over consecutive calendar quarters, blocks of
    `block`: neighbouring quarters stay together, as one origin's miss carries across them."""
    clusters = list(_clusters(rows).values())
    k = len(clusters)
    if k == 0:
        return None
    b = min(block, k)
    inside = np.array([sum(c) for c in clusters], dtype=float)
    size = np.array([len(c) for c in clusters], dtype=float)
    starts_n, per = k - b + 1, math.ceil(k / b)
    rng = np.random.Generator(np.random.PCG64(seed))
    starts = rng.integers(0, starts_n, (draws, per))
    idx = (starts[:, :, None] + np.arange(b)[None, None, :]).reshape(draws, -1)[:, :k]
    return _interval(inside[idx].sum(axis=1) / size[idx].sum(axis=1))


def verdict(
    c: Cover, interval: tuple[float, float] | None, companies: dict[str, Cover] | None = None
) -> str:
    """The pass rule of the design doc, for one item."""
    if c.share is None or interval is None:
        return "no data"
    includes = interval[0] <= TARGET <= interval[1]
    in_band = POINT_BAND[0] <= c.share <= POINT_BAND[1]
    if includes and in_band:
        each = all(
            x.share is not None and COMPANY_BAND[0] <= x.share <= COMPANY_BAND[1]
            for x in (companies or {}).values()
        )
        return "met for every company" if companies and each else "met on average"
    if includes:
        return "inconclusive"
    return "failed: too narrow" if c.share < TARGET else "failed: too wide"


def group(rows: list[dict], key) -> dict:
    out: dict = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return dict(sorted(out.items()))


def widths(rows: list[dict]) -> dict[str, float | None]:
    """Median (p90 − p10) / p50 for revenue, and / revenue p50 for EBIT (margin points)."""
    revenue_p50 = {
        (r["subject_id"], r["variant"], r["pool"], r["period"]): r["p50"]
        for r in rows
        if r["item"] == "revenue" and r["p50"] is not None
    }
    out = {}
    for item in ITEMS:
        ws = []
        for r in rows:
            if r["item"] != item or r["p10"] is None:
                continue
            scale = revenue_p50.get((r["subject_id"], r["variant"], r["pool"], r["period"]))
            if scale:
                ws.append((r["p90"] - r["p10"]) / abs(scale))
        out[item] = statistics.median(ws) if ws else None
    return out


def rolling(rows: list[dict], pool: str = "pooled") -> list[dict]:
    """The rolling test's rows: baseline ranges of origins dated ROLLING_FROM or later."""
    start = ROLLING_FROM.isoformat()
    return [
        r
        for r in rows
        if r["subject_kind"] == "origin"
        and r["variant"] == "baseline"
        and r["pool"] == pool
        and r["as_of"] >= start
    ]


def h1_ended(r: dict) -> bool:
    return r["horizon"] == 1 and r["period_end"] is not None and r["period_end"] < r["as_of"]


# -- report ------------------------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _iv(iv: tuple[float, float] | None) -> str:
    return "n/a" if iv is None else f"{100 * iv[0]:.1f}% to {100 * iv[1]:.1f}%"


def _width(item: str, w: float | None) -> str:
    if w is None:
        return "n/a"
    return f"{100 * w:.1f}% of revenue" if item == "revenue" else f"{100 * w:.1f} margin points"


def _cover_line(name: str, rows: list[dict]) -> str:
    c = cover(rows)
    return (
        f"| {name} | {c.n} | {_pct(c.share)} | {_iv(c.wilson)} | {_iv(cluster_bootstrap(rows))} "
        f"| {_pct(c.below / c.n if c.n else None)} | {_pct(c.above / c.n if c.n else None)} |"
    )


HEAD = (
    "| Group | Quarters | Coverage | Wilson 95% | Cluster bootstrap 90% | Below p10 | Above p90 |\n"
    "|---|---|---|---|---|---|---|"
)


def load_results(conn: sqlite3.Connection, build_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT r.*, o.ticker AS origin_ticker FROM range_results r "
            "LEFT JOIN forecast_origins o ON o.origin_id = r.subject_id "
            "WHERE r.build_id = ? ORDER BY r.subject_kind, r.subject_id, r.variant, r.pool, "
            "r.item, r.horizon",
            (build_id,),
        )
    ]


def _ticker(r: dict) -> str:
    return r["origin_ticker"] or r["subject_id"].split("_")[0]


def m8_rows(conn: sqlite3.Connection, batch_id: str) -> dict[tuple, dict]:
    return {
        (r["case_id"], r["variant"], r["item"], r["period"]): dict(r)
        for r in conn.execute("SELECT * FROM eval_results WHERE batch_id = ?", (batch_id,))
    }


def render(conn: sqlite3.Connection, build_id: str) -> str:
    build = conn.execute("SELECT * FROM range_builds WHERE build_id = ?", (build_id,)).fetchone()
    rows = load_results(conn, build_id)
    origins = conn.execute(
        "SELECT status, COUNT(*) AS n FROM forecast_origins GROUP BY status"
    ).fetchall()
    lines = [
        f"# Honest ranges: build {build_id}",
        "",
        f"Code version `{build['code_version']}`; actuals as first reported, as of "
        f"{build['actuals_as_of']}; backtest batch {build['eval_batch_id'] or 'none'}. "
        "Design: `docs/designs/m9-honest-ranges.md`. Origins: "
        + ", ".join(f"{r['n']} {r['status']}" for r in origins)
        + ".",
        "",
        "Each forecast quarter's p10–p90 range is the forecast with the baseline's past misses "
        "applied to it, using only misses whose actual had been filed by the forecast's date. "
        "Decision 7 asks that about 80% of actuals fall inside.",
        "",
        "## The pass rule (rolling test, pooled, baseline range, all horizons)",
        "",
        "| Item | Quarters | Coverage | Cluster bootstrap 90% | Block bootstrap 90% | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for item in ITEMS:
        rs = [r for r in rolling(rows) if r["item"] == item]
        c, iv = cover(rs), cluster_bootstrap(rs)
        companies = {t: cover(g) for t, g in group(scored(rs), _ticker).items()}
        lines.append(
            f"| {item} | {c.n} | {_pct(c.share)} | {_iv(iv)} | {_iv(block_bootstrap(rs))} "
            f"| **{verdict(c, iv, companies)}** |"
        )
    lines += [
        "",
        "Met on average: coverage 70–90% and the cluster bootstrap interval includes 80%. Met for "
        "every company: also each company 65–95%. Inconclusive: the interval includes 80% but "
        "coverage is outside 70–90%. Clusters are calendar quarters of the actual "
        f"({len(_clusters([r for r in rolling(rows) if r['item'] == 'revenue']))} for revenue).",
    ]
    for pool in POOLS:
        for item in ITEMS:
            rs = [r for r in rolling(rows, pool) if r["item"] == item]
            lines += ["", f"## Rolling test, {pool}, {item}", "", HEAD]
            lines.append(_cover_line("all", rs))
            for h, g in group(rs, lambda r: r["horizon"]).items():
                lines.append(_cover_line(f"h{h}", g))
            h1 = [r for r in rs if r["horizon"] == 1]
            lines.append(_cover_line("h1, quarter already ended", [r for r in h1 if h1_ended(r)]))
            lines.append(
                _cover_line("h1, quarter still running", [r for r in h1 if not h1_ended(r)])
            )
            for t, g in group(rs, _ticker).items():
                lines.append(_cover_line(t, g))
            years = group(scored(rs), lambda r: r["period_end"][:4])
            for y, g in years.items():
                lines.append(_cover_line(f"actuals in {y}", g))
            no_hist = sum(r["status"] == "no_history" for r in rs)
            w = widths(rolling(rows, pool))
            lines += [
                "",
                f"Quarters with no range (not enough history): {no_hist}. Median width "
                f"(p90 − p10): {_width(item, w[item])}.",
            ]
    warm = [
        r for r in rows if r["subject_kind"] == "origin" and r["as_of"] < ROLLING_FROM.isoformat()
    ]
    lines += ["", "## Warm-up origins (before the rolling test; information only)", "", HEAD]
    for item in ITEMS:
        lines.append(
            _cover_line(item, [r for r in warm if r["item"] == item and r["pool"] == "pooled"])
        )

    cases = [r for r in rows if r["subject_kind"] == "case"]
    if cases:
        m8 = m8_rows(conn, build["eval_batch_id"])
        lines += [
            "",
            "## The 26 cases (pooled), against the M8 bands",
            "",
            "Too few to pass or fail on their own. M8's bands hold shock size only; the "
            "baseline's M8 band is its point forecast. Interval score: Gneiting & Raftery "
            "(2007) at α = 0.2, divided by actual revenue (lower is better), on the same quarters.",
            "",
            "| Variant | Item | Quarters | Coverage now | Coverage in M8 | Interval score now "
            "| Interval score in M8 | No range |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for (variant, item), g in group(
            [r for r in cases if r["pool"] == "pooled"], lambda r: (r["variant"], r["item"])
        ).items():
            rs = scored(g)
            now_is, then_is, then_in = [], [], 0
            for r in rs:
                old = m8.get((r["subject_id"], variant, item, r["period"]))
                if old is None:
                    continue
                lo, hi = (old["p10"], old["p90"]) if old["p10"] is not None else (
                    old["forecast"], old["forecast"])  # fmt: skip
                then_in += lo <= r["actual"] <= hi
                now_is.append(interval_score(r["p10"], r["p90"], r["actual"], r["actual_revenue"]))
                then_is.append(interval_score(lo, hi, r["actual"], r["actual_revenue"]))
            c = cover(rs)
            lines.append(
                f"| {variant} | {item} | {c.n} | {_pct(c.share)} "
                f"| {_pct(then_in / len(now_is) if now_is else None)} "
                f"| {statistics.fmean(now_is):.3f} | {statistics.fmean(then_is):.3f} "
                f"| {sum(r['status'] == 'no_history' for r in g)} |"
                if now_is
                else f"| {variant} | {item} | {c.n} | {_pct(c.share)} | n/a | n/a | n/a "
                f"| {sum(r['status'] == 'no_history' for r in g)} |"
            )
    lines += [
        "",
        "## Limitations",
        "",
        "- Monthly origins overlap: about three origins forecast each quarter, so errors are "
        "counted about three times and quarters are not independent (hence the cluster and "
        "block bootstraps; the Wilson interval assumes independence and is too narrow).",
        "- Errors cluster in crises (2020, 2022); an expanding window weights every past year "
        "the same.",
        "- With shocks, the baseline's past error is assumed independent of the shock's size; "
        "where a shock captures an event that past errors also hold, the range leans wide.",
        "- Revenue and EBIT only; the valuation has no range yet.",
        "- One-off GAAP charges (P&G FY2019Q4 Gillette impairment, Exxon FY2020Q4 impairment, "
        "J&J FY2023Q1 talc charge) sit in the EBIT tails; scope changes (Kenvue, 2023) and "
        "14-week quarters (AAPL FY2023Q1) score as misses.",
        "",
    ]
    return "\n".join(lines)
