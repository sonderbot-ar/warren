"""Markdown report of an evaluation batch, built from the database alone.

The headline is the median error by item and horizon, for the baseline and the naive seasonal
random walk, because a few skewed cases would dominate a mean. Every case and every failure is
listed, so nothing that went wrong is hidden by the summary.
"""

import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

from shared_kernel.config import REPORTS_DIR as ALL_REPORTS_DIR

REPORTS_DIR = ALL_REPORTS_DIR / "eval"
ITEMS = ("revenue", "ebit")
ITEM_LABELS = {"revenue": "Revenue (absolute % error)", "ebit": "EBIT (margin points)"}


def _err(item: str, value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:.1%}" if item == "revenue" else f"{value * 100:.2f} pts"


def _m(value: float | None) -> str:
    return "–" if value is None else f"{value / 1e6:,.0f}"


def _quartiles(values: list[float]) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    q = statistics.quantiles(values, n=4, method="inclusive")
    return q[0], q[2]


def load_rows(conn: sqlite3.Connection, batch_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT r.*, c.event_type, c.scope_change FROM eval_results r "
            "JOIN eval_cases c USING (case_id) WHERE batch_id = ? "
            "ORDER BY c.event_date, r.case_id, r.item, r.period, r.variant",
            (batch_id,),
        )
    ]


def pairs(rows: list[dict]) -> list[dict]:
    """Scored quarters with the baseline and naive side by side: one dict per case/item/period."""
    paired: dict[tuple, dict] = defaultdict(dict)
    for r in rows:
        if r["status"] == "ok":
            paired[(r["case_id"], r["item"], r["period"])][r["variant"]] = r
    return [p for p in paired.values() if {"baseline", "naive_srw"} <= set(p)]


def summary(rows: list[dict]) -> dict[tuple[str, int | None], dict]:
    """By (item, horizon) and (item, None) for all horizons: medians, IQR, beat share, counts."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for p in pairs(rows):
        base = p["baseline"]
        groups[(base["item"], base["horizon"])].append(p)
        groups[(base["item"], None)].append(p)
    out = {}
    for key, group in groups.items():
        base = [p["baseline"]["error"] for p in group]
        naive = [p["naive_srw"]["error"] for p in group]
        directions = [
            p["baseline"]
            for p in group
            if p["baseline"]["direction_actual"] is not None
            and p["baseline"]["direction_forecast"] is not None
        ]
        out[key] = {
            "n": len(group),
            "baseline": statistics.median(base),
            "naive": statistics.median(naive),
            "iqr": _quartiles(base),
            "beat": sum(b < n for b, n in zip(base, naive, strict=True)) / len(group),
            "hits": (
                sum(r["direction_forecast"] == r["direction_actual"] for r in directions)
                / len(directions)
                if directions
                else None
            ),
            "base_rate": (
                sum(r["direction_actual"] == 1 for r in directions) / len(directions)
                if directions
                else None
            ),
        }
    return out


def _segment(rows: list[dict], keep) -> str:
    chosen = [p for p in pairs(rows) if keep(p["baseline"])]
    cells = []
    for item in ITEMS:
        group = [p for p in chosen if p["baseline"]["item"] == item]
        if not group:
            cells.append("–")
            continue
        base = statistics.median(p["baseline"]["error"] for p in group)
        naive = statistics.median(p["naive_srw"]["error"] for p in group)
        cells.append(f"{_err(item, base)} vs {_err(item, naive)} (n={len(group)})")
    return " | ".join(cells)


def render(conn: sqlite3.Connection, batch_id: str) -> str:
    batch = conn.execute("SELECT * FROM eval_batches WHERE batch_id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError(f"no evaluation batch {batch_id}")
    rows = load_rows(conn, batch_id)
    failures = conn.execute(
        "SELECT case_id, reason FROM eval_failures WHERE batch_id = ? ORDER BY case_id",
        (batch_id,),
    ).fetchall()
    cases = sorted({r["case_id"] for r in rows})
    incomplete = sorted({r["case_id"] for r in rows if r["status"] == "missing"})
    stats = summary(rows)

    out = [
        f"# Evaluation batch {batch_id}",
        "",
        f"Created {batch['created_at']} · code `{batch['code_version']}` · case file "
        f"`{batch['cases_sha256'][:12]}`",
        f"Cases scored: {len(cases)} · failed: {len(failures)} · incomplete (some quarters not "
        f"reported yet): {len(incomplete)}",
        "",
        "## Headline: median error, baseline vs naive",
        "",
        "Naive is a seasonal random walk: each quarter forecast as the same quarter a year "
        "earlier. The baseline has to beat it to be worth anything.",
        "",
        "| Item | Horizon | n | Baseline (median) | Naive (median) | Baseline IQR | "
        "Baseline beat naive | Direction hits | Base rate (up) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in ITEMS:
        for horizon in (1, 2, 3, 4, None):
            s = stats.get((item, horizon))
            if s is None:
                continue
            iqr = s["iqr"]
            out.append(
                f"| {ITEM_LABELS[item]} | {'all' if horizon is None else f'h{horizon}'} | "
                f"{s['n']} | {_err(item, s['baseline'])} | {_err(item, s['naive'])} | "
                + (f"{_err(item, iqr[0])} – {_err(item, iqr[1])}" if iqr else "–")
                + f" | {s['beat']:.0%} | "
                + ("–" if s["hits"] is None else f"{s['hits']:.0%}")
                + " | "
                + ("–" if s["base_rate"] is None else f"{s['base_rate']:.0%}")
                + " |"
            )
    out += [
        "",
        "## Segments (median baseline vs naive, all horizons)",
        "",
        "| Segment | Revenue | EBIT |",
        "|---|---|---|",
        f"| Events | {_segment(rows, lambda r: r['event_type'] != 'control')} |",
        f"| Controls | {_segment(rows, lambda r: r['event_type'] == 'control')} |",
        f"| Without scope changes | {_segment(rows, lambda r: not r['scope_change'])} |",
        f"| Without derived Q4 actuals | {_segment(rows, lambda r: not r['derived'])} |",
        "",
        "Results by event type would be about two cases each: descriptive only, not shown.",
        "",
        "## Every case",
        "",
        "| Case | Type | Quarter | h | Item | Baseline | Naive | Actual (first reported) | "
        "Baseline error | Naive error | Flags |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in sorted(
        pairs(rows), key=lambda p: (p["baseline"]["case_id"], p["baseline"]["item"],
                                    p["baseline"]["period"])
    ):  # fmt: skip
        b, n = p["baseline"], p["naive_srw"]
        flags = ", ".join(
            f for f, on in (("derived Q4", b["derived"]), ("scope change", b["scope_change"])) if on
        )
        out.append(
            f"| {b['case_id']} | {b['event_type']} | {b['period']} | {b['horizon']} | "
            f"{b['item']} | {_m(b['forecast'])} | {_m(n['forecast'])} | {_m(b['actual'])} | "
            f"{_err(b['item'], b['error'])} | {_err(b['item'], n['error'])} | {flags} |"
        )
    out += ["", "Amounts in millions.", ""]
    out += _with_shocks(rows)
    if incomplete:
        out += ["## Incomplete cases", "", *[f"- {c}" for c in incomplete], ""]
    out += ["## Failed cases", ""]
    out += [f"- **{f['case_id']}**: {f['reason']}" for f in failures] or ["None."]
    out += [
        "",
        "## Glossary",
        "",
        "- **Absolute % error (revenue):** |forecast − actual| ÷ |actual|.",
        "- **Margin points (EBIT):** |forecast − actual| ÷ actual revenue. Unlike a percentage "
        "of EBIT, it stays meaningful when EBIT is near zero or negative.",
        "- **First reported:** the actual as the company first published it, not a later "
        "restatement, so the forecast is judged on what could have been known.",
        "- **Direction hit:** forecast and actual move the same way against the same quarter a "
        "year earlier (within ±0.5% counts as flat). Compare it with the base rate: a forecast "
        "that always says 'up' hits as often as quarters rise.",
        "- **Baseline beat naive:** share of quarters where the baseline's error was smaller.",
        "",
        "## Limitations",
        "",
        "- Events were chosen in hindsight as notable. Controls and the naive benchmark are the "
        "check against that.",
        "- About 24 cases: medians and shares are rough. Later milestones compare per case "
        "(paired), not by differences of averages.",
        "- Derived Q4 actuals carry any 10-K recast into Q4; scope changes add an acquired "
        "business to the actuals. Both are shown apart above.",
    ]
    return "\n".join(out) + "\n"


def _with_shocks(rows: list[dict]) -> list[str]:
    """Cases simulated under shocks from company guidance (M4): p50 scored next to the baseline."""
    shocked = {
        (r["case_id"], r["item"], r["period"]): r for r in rows if r["variant"] == "with_shocks"
    }
    if not shocked:
        return []
    base = {(r["case_id"], r["item"], r["period"]): r for r in rows if r["variant"] == "baseline"}
    out = [
        "## With shocks from company guidance",
        "",
        "The baseline run again under shocks converted by code from the company's own revised "
        "guidance. The p10–p90 band covers only the uncertainty in the shocks' size, so it is "
        "narrower than the true uncertainty; a guided range's ends are read as p10 and p90, an "
        "assumption checked later. Three cases show the plumbing works, not that shocks help.",
        "",
        "| Case | Quarter | Item | Baseline | With shocks p10 / p50 / p90 | Actual | "
        "Baseline error | With shocks error |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key in sorted(shocked):
        r, b = shocked[key], base.get(key)
        scored = r["status"] == "ok"
        out.append(
            f"| {r['case_id']} | {r['period']} | {r['item']} | "
            f"{_m(b['forecast']) if b else 'n/a'} | "
            f"{_m(r['p10'])} / {_m(r['p50'])} / {_m(r['p90'])} | "
            f"{_m(r['actual']) if scored else 'not yet reported'} | "
            f"{_err(r['item'], b['error']) if b and scored else 'n/a'} | "
            f"{_err(r['item'], r['error']) if scored else 'n/a'} |"
        )
    return [*out, ""]


def write_report(conn: sqlite3.Connection, batch_id: str, directory: Path = REPORTS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{batch_id}.md"
    path.write_text(render(conn, batch_id))
    return path
