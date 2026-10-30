"""Markdown report of a Monte Carlo simulation: baseline vs shocked, period by period (M4)."""

import sqlite3
from pathlib import Path

from domains.analysis.montecarlo import LINES, load_bands, load_simulation_shocks
from domains.analysis.schemas import SINGLE
from shared_kernel.config import REPORTS_DIR as ALL_REPORTS_DIR

REPORTS_DIR = ALL_REPORTS_DIR / "sim"
LINE_LABELS = {"revenue": "Revenue", "ebit": "Operating income (EBIT)", "fcff": "Free cash flow"}
UNITS = {"risk_premium": "bp"}


def _m(value: float) -> str:
    return f"{value / 1e6:,.0f}"


def render(conn: sqlite3.Connection, sim_id: str) -> str:
    sim = conn.execute(
        "SELECT s.*, r.ticker, r.as_of FROM simulations s JOIN runs r USING (run_id) "
        "WHERE sim_id = ?",
        (sim_id,),
    ).fetchone()
    bands = load_bands(conn, sim_id)
    cur = sim["currency"]
    vps = bands[("value_per_share", SINGLE)]
    lines = [
        f"# Shocked DCF: {sim['ticker']} as of {sim['as_of']}",
        "",
        f"Simulation `{sim_id}` of run `{sim['run_id']}` · {sim['n_samples']:,} samples · "
        f"seed {sim['seed']} · created {sim['created_at']}",
        "",
        "What the shocks below would do to the forecast, and when. It is not a forecast of the "
        "share price.",
        "",
        "## Summary",
        "",
        f"- **Value per share:** baseline {vps.baseline:,.2f}; with the shocks p10 {vps.p10:,.2f}"
        f" · p50 {vps.p50:,.2f} · p90 {vps.p90:,.2f} ({cur})",
        "- The range covers **only the uncertainty in the shocks' size**. The baseline's own "
        "drivers are not sampled, so the true uncertainty is wider.",
        "- Percentiles don't add up: the p50s of the quarters don't sum to the p50 of a year or "
        "of the value.",
        "",
        "## Shocks",
        "",
        "| Shock | Driver | p10 / p50 / p90 | Starts | Lasts | Decay | Source | Why |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in load_simulation_shocks(conn, sim_id):
        unit = UNITS.get(s.driver, "pts")
        lines.append(
            f"| {s.shock_id} | {s.driver} | {s.low:g} / {s.base:g} / {s.high:g} {unit} | "
            f"quarter {s.start_period} | {s.horizon} q | {s.decay:g} | {s.source} | "
            f"{s.rationale} |"
        )
    lines += [
        "",
        "A growth shock changes a quarter's level, and the same quarter a year later grows from "
        "that new level, so even a one-quarter growth shock stays in revenue for good.",
    ]
    periods = [p for (name, p) in bands if name == "revenue"]
    periods.sort(key=lambda p: (p.startswith("Y"), p))
    for line in LINES:
        lines += [
            "",
            f"## {LINE_LABELS[line]} ({cur} millions)",
            "",
            "| Period | Baseline | p10 | p50 | p90 | p50 vs baseline |",
            "|---|---|---|---|---|---|",
        ]
        for period in periods:
            b = bands[(line, period)]
            change = f"{b.p50 / b.baseline - 1:+.1%}" if b.baseline else "n/a"
            lines.append(
                f"| {period} | {_m(b.baseline)} | {_m(b.p10)} | {_m(b.p50)} | {_m(b.p90)} | "
                f"{change} |"
            )
    return "\n".join(lines) + "\n"


def write_report(conn: sqlite3.Connection, sim_id: str, reports_dir: Path | None = None) -> Path:
    reports_dir = REPORTS_DIR if reports_dir is None else reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{sim_id}.md"
    path.write_text(render(conn, sim_id))
    return path
