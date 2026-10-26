"""Markdown report of a stored DCF run, built from the database alone (runs and their rows)."""

import sqlite3
from pathlib import Path

from domains.analysis import dcf
from domains.analysis.runs import load_assumptions, load_outputs
from domains.analysis.schemas import SINGLE
from shared_kernel.config import REPORTS_DIR as ALL_REPORTS_DIR

REPORTS_DIR = ALL_REPORTS_DIR / "dcf"
DRIVER_LABELS = {
    "revenue_growth": "Revenue growth",
    "operating_margin": "Operating margin",
    "tax_rate": "Tax rate",
    "da_pct": "D&A / revenue",
    "capex_pct": "Capex / revenue",
    "nwc_pct": "Working capital / revenue",
}
LINE_LABELS = {
    "revenue": "Revenue",
    "ebit": "EBIT",
    "nopat": "EBIT × (1 − tax)",
    "d_and_a": "+ D&A",
    "capex": "− Capex",
    "delta_nwc": "− Δ working capital",
    "fcff": "**Free cash flow**",
    "discount_factor": "Discount factor",
}


def _m(value: float) -> str:
    return f"{value / 1e6:,.0f}"


def _pct(value: float) -> str:
    return f"{value:.2%}"


def render(conn: sqlite3.Connection, run_id: str) -> str:
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    company = conn.execute("SELECT * FROM companies WHERE cik = ?", (run["cik"],)).fetchone()
    rows = load_assumptions(conn, run_id)
    by_key = {(a.name, a.period): a for a in rows}
    out = load_outputs(conn, run_id)

    def a(name: str, period: str = SINGLE) -> float:
        return by_key[(name, period)].value

    def o(name: str, period: str = SINGLE) -> float:
        return out[(name, period)]

    periods = sorted(p for (n, p) in by_key if n == "revenue_growth")
    price = by_key[("price", SINGLE)]
    lines = [
        f"# DCF: {run['ticker']} as of {run['as_of']}",
        "",
        f"{company['name']} · CIK {run['cik']} · run `{run_id}` · created {run['created_at']}",
        "",
        "A baseline valuation of the business from its reported numbers and documented rules. "
        "It is not a forecast of the share price.",
        "",
        "## Summary",
        "",
        f"- **Value per share: {o('value_per_share'):,.2f}** "
        f"(share price {price.value:,.2f}, {price.method.split(' (')[0]}, for comparison only)",
        f"- At ERP ± 1 standard error: {_sensitivity(out)}",
        f"- Enterprise value {_m(o('enterprise_value_as_of'))}M · equity value "
        f"{_m(o('equity_value'))}M (USD millions)",
        f"- WACC {_pct(o('wacc'))} · terminal growth {_pct(a('terminal_growth'))} · terminal "
        f"value {o('terminal_share'):.0%} of enterprise value",
        "",
        "## Cost of capital",
        "",
        "| Input | Value | Source |",
        "|---|---|---|",
    ]
    for name, label in [
        ("risk_free", "Risk-free rate"),
        ("beta", "Beta"),
        ("erp", "Equity risk premium"),
        ("erp_std_error", "ERP standard error"),
        ("info:erp_arithmetic", "ERP, arithmetic (information)"),
        ("info:erp_from_1999", "ERP from 1999 (information)"),
        ("info:erp_from_2009", "ERP from 2009 (information)"),
        ("cost_of_debt", "Cost of debt (pre-tax)"),
        ("debt_tax_rate", "Tax rate on debt"),
        ("terminal_growth", "Terminal growth"),
    ]:
        if (name, SINGLE) in by_key:
            value = a(name)
            shown = f"{value:.2f}" if name == "beta" else _pct(value)
            lines.append(f"| {label} | {shown} | {by_key[(name, SINGLE)].method} |")
    equity, debt = a("equity_market_value"), a("debt")
    lines += [
        f"| Cost of equity | {_pct(o('cost_of_equity'))} | risk-free + beta × ERP |",
        f"| Weights | equity {equity / (equity + debt):.1%} · debt {debt / (equity + debt):.1%} | "
        f"market value of equity {_m(equity)}M, book debt {_m(debt)}M |",
        f"| **WACC** | **{_pct(o('wacc'))}** | |",
        "",
        "## Drivers",
        "",
        "| Driver | " + " | ".join(periods) + " |",
        "|---|" + "---|" * len(periods),
    ]
    for name, label in DRIVER_LABELS.items():
        lines.append(f"| {label} | " + " | ".join(_pct(a(name, p)) for p in periods) + " |")
    lines += [""]
    for name, label in DRIVER_LABELS.items():
        lines.append(f"- **{label}**: {by_key[(name, periods[-1])].method}")
    if "Q" in periods[0]:
        lines.append(f"- **Quarterly margins**: {by_key[('operating_margin', periods[0])].method}")
    seed = sorted((p, r) for (n, p), r in by_key.items() if n == dcf.SEED)
    lines.append(
        "- **Revenue seed** (last 4 actual quarters, USD millions): "
        + "; ".join(f"{p} {_m(r.value)} ({r.method})" for p, r in seed)
    )

    lines += [
        "",
        "## Free cash flow (USD millions)",
        "",
        "| | " + " | ".join(periods) + " |",
        "|---|" + "---|" * len(periods),
    ]
    for name, label in LINE_LABELS.items():
        fmt = (lambda v: f"{v:.4f}") if name == "discount_factor" else _m
        lines.append(f"| {label} | " + " | ".join(fmt(o(name, p)) for p in periods) + " |")

    lines += [
        "",
        "## From enterprise value to value per share (USD millions)",
        "",
        "| | |",
        "|---|---|",
        f"| Present value of forecast cash flows | {_m(o('pv_explicit'))} |",
        f"| Present value of terminal value ({_m(o('terminal_value'))} at the end of Y5) | "
        f"{_m(o('pv_terminal'))} |",
        f"| Enterprise value at the last quarter end | {_m(o('enterprise_value'))} |",
        f"| Carried to the as-of date ({a('roll_years'):.3f} years at WACC) | "
        f"{_m(o('enterprise_value_as_of'))} |",
        f"| − Debt | {_m(debt)} |",
        f"| + Cash and investments | {_m(a('cash_and_investments'))} |",
        f"| − Minority interest | {_m(a('minority_interest'))} |",
        f"| **Equity value** | **{_m(o('equity_value'))}** |",
        f"| ÷ Shares (millions) | {a('shares') / 1e6:,.1f} |",
        f"| **Value per share** | **{o('value_per_share'):,.2f}** |",
        "",
        f"- Debt: {by_key[('debt', SINGLE)].method}",
        f"- Shares: {by_key[('shares', SINGLE)].method}",
        f"- Minority interest: {by_key[('minority_interest', SINGLE)].method}",
        "",
        "## Inputs and fallbacks",
        "",
        "Every reported value the run used, with its tag and filing. Fallbacks (owner decision D8) "
        "are marked.",
        "",
        "| Input | Period | Value (USD millions) | Source |",
        "|---|---|---|---|",
    ]
    for r in rows:
        if r.name.startswith(("history:", "balance:")):
            mark = " **(fallback)**" if r.method.startswith("fallback") else ""
            lines.append(
                f"| {r.name.split(':', 1)[1]}{mark} | {r.period} | {_m(r.value)} | {r.method} |"
            )

    notes = [n for n in (run["notes"] or "").split("\n") if n]
    lines += ["", "## Warnings", ""] + ([f"- {n}" for n in notes] or ["None."])
    lines += [
        "",
        "## Owner's choices",
        "",
    ]
    lines += [f"- **{r.name}**: {r.method}" for r in rows if r.source == "user"]
    lines += [
        "",
        "## Data snapshot",
        "",
        f"- Code version `{run['code_version']}`",
        f"- Fundamentals: ingest run {run['ingest_run_id']}, concept map "
        f"`{run['concept_map_sha256'][:12]}`",
        f"- Prices `{run['price_fetch_sha256'][:12]}` · index `{run['index_fetch_sha256'][:12]}` "
        f"· risk-free `{run['yield_fetch_sha256'][:12]}` (content hashes of the downloads)",
        f"- Reproduce: `python -m domains.analysis reproduce --run-id {run_id}`",
    ]
    return "\n".join(lines) + "\n"


def _sensitivity(out: dict) -> str:
    parts = []
    for name, label in (("erp_minus_1se", "−1 SE"), ("erp_plus_1se", "+1 SE")):
        value = out.get((f"value_per_share_{name}", SINGLE))
        parts.append(
            f"{label} {value:,.2f}" if value is not None else f"{label} no value (WACC ≤ growth)"
        )
    return " · ".join(parts)


def write_report(conn: sqlite3.Connection, run_id: str, reports_dir: Path = REPORTS_DIR) -> Path:
    run = conn.execute("SELECT ticker, as_of FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{run['ticker']}_{run['as_of']}.md"
    path.write_text(render(conn, run_id))
    return path
