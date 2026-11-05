"""Where each assumption of a run came from, as fields (backlog #175).

Every row a run stores (`assumptions`) gets a list of typed sources beside its English `method`
text, so the student app's *Fuente* tab can link a number to its filing, its market series, the
owner's choice or the other rows it was computed from, without parsing text. Sources describe
rows; they never move a number, so `reproduce` and `rebuild` don't read them.

Kinds:
- `filing`: one EDGAR fact (a reported one with its accession, or one Warren derived, e.g. Q4 =
  year − nine months, with the accessions it used).
- `market`: one downloaded series over a day or a span (Yahoo Finance or FRED); the download is
  the one the run's data snapshot names.
- `owner_choice`: a row of `user_assumptions.csv`.
- `derived`: computed from other rows of the same run.
- `rule`: a value set by a fixed rule with no data behind it (an item not reported, counted as
  zero; no debt, so no cost of debt).
- `what_if`: a row a student changed on a what-if child (backlog #141), with the parent's sources.
"""

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from urllib.parse import quote

from domains.analysis.schemas import SINGLE as SINGLE_PERIOD
from domains.analysis.schemas import Assumption
from domains.fundamentals.schemas import Fact
from domains.market.prices import MARKET_INDEX
from domains.market.yields import RISK_FREE_SERIES

KINDS = ("filing", "market", "owner_choice", "derived", "rule", "what_if")
RULES = {
    "not_reported_zero": "Not reported within a year of the balance sheet: counted as zero.",
    "no_debt": "No debt on the balance sheet: the cost of debt is not used (its weight is 0).",
    "not_in_annual_report_zero": "Not reported in that year's annual report: counted as zero.",
}
PROVIDERS = {"yahoo": "Yahoo Finance", "fred": "FRED"}
MEASURES = ("close", "splits", "weekly_total_return", "annual_total_return", "yield")
NOT_RECORDED = {
    "code": "not_recorded",
    "params": {},
    "text": "This run was stored before sources were recorded; see the method text.",
}


class SourceError(ValueError):
    """A run's sources are incomplete or malformed: a row without one, an unknown kind, or a
    derived input that names no row of the run."""


Key = tuple[str, str]  # (name, period) of an assumption row


def filing(fact: Fact) -> dict:
    """One EDGAR fact, as the point-in-time query returned it."""
    return {
        "kind": "filing",
        "item": fact.canonical_name,
        "concept": fact.xbrl_concept,
        "unit": fact.unit,
        "period_start": fact.period_start.isoformat() if fact.period_start else None,
        "period_end": fact.period_end.isoformat(),
        "fiscal_year": fact.fiscal_year,
        "fiscal_period": fact.fiscal_period,
        "value": fact.value,
        "filed_at": fact.filed_at.isoformat(),
        "accession_no": fact.accession_no,
        "inputs": list(fact.inputs),
        "derived": fact.derived,
        "restated": fact.restated,
    }


def market(provider: str, series: str, measure: str, start: date, end: date) -> dict:
    """A downloaded series over [start, end] (one day when equal). Which download: the one whose
    hash the run stores for that series (`runs.price_fetch_sha256`, `index_fetch_sha256`,
    `yield_fetch_sha256`), added when the sources are read."""
    if provider not in PROVIDERS:
        raise SourceError(f"unknown market provider {provider!r}")
    if measure not in MEASURES:
        raise SourceError(f"unknown market measure {measure!r}")
    return {
        "kind": "market",
        "provider": provider,
        "series": series,
        "measure": measure,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def owner_choice(name: str, value: str, set_by: str, set_on: str) -> dict:
    return {
        "kind": "owner_choice",
        "choice": name,
        "value": value,
        "set_by": set_by,
        "set_on": set_on,
    }


def derived(*inputs: Key) -> dict:
    """Computed from these rows of the same run."""
    if not inputs:
        raise SourceError("a derived source needs at least one input row")
    return {"kind": "derived", "inputs": [{"name": n, "period": p} for n, p in inputs]}


def rule(code: str) -> dict:
    if code not in RULES:
        raise SourceError(f"unknown rule {code!r}")
    return {"kind": "rule", "code": code}


def what_if(parent_run_id: str, before: float | None, how: str, parent_sources: list) -> dict:
    return {
        "kind": "what_if",
        "parent_run_id": parent_run_id,
        "before": before,
        "how": how,
        "parent_sources": list(parent_sources),
    }


def check(rows: Iterable[Assumption], sources: dict[Key, list[dict]], child: bool = False) -> None:
    """Every row has at least one source of a known kind, every source belongs to a row, every
    derived input names a row of the run, and `what_if` appears only on a what-if child."""
    keys = {(a.name, a.period) for a in rows}
    missing = sorted(keys - sources.keys())
    if missing:
        raise SourceError(f"rows without a source: {missing}")
    extra = sorted(sources.keys() - keys)
    if extra:
        raise SourceError(f"sources for rows the run doesn't store: {extra}")
    for key, items in sources.items():
        if not items:
            raise SourceError(f"{key}: no source")
        for item in items:
            kind = item.get("kind")
            if kind not in KINDS:
                raise SourceError(f"{key}: unknown kind {kind!r}")
            if kind == "what_if" and not child:
                raise SourceError(f"{key}: a what_if source on a run that is not a what-if")
            for inner in [item] + list(item.get("parent_sources", [])):
                if inner.get("kind") != "derived":
                    continue
                for ref in inner["inputs"]:
                    if "run_id" in ref:  # a parent's row, on a what-if child
                        if not child:
                            raise SourceError(f"{key}: an input from another run on a base run")
                        continue
                    if (ref["name"], ref["period"]) not in keys:
                        raise SourceError(f"{key}: derived from {ref}, which the run doesn't store")


def insert(conn: sqlite3.Connection, run_id: str, sources: dict[Key, list[dict]]) -> None:
    """Store a run's sources; the caller holds the write transaction (`runs.write_lock`)."""
    conn.executemany(
        "INSERT INTO assumption_sources (run_id, name, period, position, kind, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                name,
                period,
                i,
                item["kind"],
                json.dumps({k: v for k, v in item.items() if k != "kind"}, sort_keys=True),
            )
            for (name, period), items in sorted(sources.items())
            for i, item in enumerate(items)
        ],
    )


def load(conn: sqlite3.Connection, run_id: str) -> dict[Key, list[dict]]:
    """A run's stored sources by row, in the order they were written; {} for a run made before
    sources were recorded."""
    out: dict[Key, list[dict]] = {}
    for r in conn.execute(
        "SELECT name, period, kind, detail FROM assumption_sources WHERE run_id = ? "
        "ORDER BY name, period, position",
        (run_id,),
    ):
        out.setdefault((r["name"], r["period"]), []).append(
            {"kind": r["kind"], **json.loads(r["detail"])}
        )
    return out


def for_child(
    parent: dict[Key, list[dict]], parent_run_id: str, changed: dict[Key, tuple[float, str]]
) -> dict[Key, list[dict]]:
    """A what-if child's sources from its parent's: a changed row (key -> (before, how)) gets a
    `what_if` source holding the parent's list; a copied row keeps the parent's list, except that
    a derived input the child changed names the parent's row (`run_id`), since the copied value
    was computed from the parent's, not the child's (analyst, #175)."""
    out: dict[Key, list[dict]] = {}
    for key in changed.keys() - parent.keys():  # a row the parent doesn't have (WACC set, #171)
        before, how = changed[key]
        out[key] = [what_if(parent_run_id, before, how, [])]
    for key, items in parent.items():
        if key in changed:
            before, how = changed[key]
            out[key] = [what_if(parent_run_id, before, how, items)]
            continue
        copied = []
        for item in items:
            if item["kind"] == "derived":
                item = {
                    "kind": "derived",
                    "inputs": [
                        ref | {"run_id": parent_run_id}
                        if (ref["name"], ref["period"]) in changed
                        else ref
                        for ref in item["inputs"]
                    ],
                }
            copied.append(item)
        out[key] = copied
    return out


# -- the output trace (item 7) -------------------------------------------------------------------

# Codes for how each output is computed from its inputs, in dcf.compute; the app owns the words.
FORMULAS = {
    "revenue_from_growth_vs_year_earlier": "the same quarter a year earlier × (1 + growth)",
    "revenue_year_from_last_four_quarters": "the last four forecast quarters × (1 + growth)",
    "revenue_from_growth": "the year before × (1 + growth)",
    "revenue_times_margin": "revenue × operating margin",
    "revenue_times_da_share": "revenue × D&A share of revenue",
    "revenue_times_capex_share": "revenue × capex share of revenue",
    "ebit_after_tax": "EBIT × (1 − tax rate)",
    "change_in_working_capital": "working-capital share × trailing revenue, less the period before",
    "first_change_in_working_capital": (
        "working-capital share × (this quarter's revenue − the same quarter a year earlier)"
    ),
    "fcff": "EBIT × (1 − tax rate) + D&A − capex − change in working capital",
    "discount_factor": "the period before's factor ÷ (1 + WACC) over the period's length",
    "capm": "risk-free rate + beta × equity risk premium",
    "wacc": "cost of equity and after-tax cost of debt, weighted by market equity and debt",
    "present_value_of_cash_flows": "Σ FCFF × discount factor",
    "gordon_terminal_value": "last FCFF × (1 + g) ÷ (WACC − g)",
    "value_driver_terminal_value": "last NOPAT × (1 + g) ÷ WACC",
    "discounted_terminal_value": "terminal value × the last discount factor",
    "sum_of_present_values": "present value of the cash flows + of the terminal value",
    "terminal_share": "present value of the terminal value ÷ enterprise value",
    "rolled_forward": "enterprise value × (1 + WACC) ^ years to the as-of date",
    "net_debt": "debt − cash and investments",
    "equity_value": "enterprise value − net debt − minority interest",
    "per_share": "equity value ÷ shares",
    "wacc_set_directly": "WACC as the what-if set it, in place of the computed one",
    "revalued_at_erp_minus_1se": "value per share with the ERP one standard error lower",
    "revalued_at_erp_plus_1se": "value per share with the ERP one standard error higher",
}


def _row(name: str, period: str) -> dict:
    return {"of": "row", "name": name, "period": period}


def _out(name: str, period: str) -> dict:
    return {"of": "output", "name": name, "period": period}


def output_trace(rows: Iterable[Assumption]) -> dict[Key, dict]:
    """Each output a run stores: its formula code and its direct inputs, rows of the run or
    other outputs, following `dcf.compute` step by step (nothing stored; from the periods)."""
    from domains.analysis import dcf  # dcf is a sibling the engine imports first

    rows = list(rows)
    index = dcf._index(rows)
    seed, periods = dcf.forecast_periods(index)
    q = dcf.QUARTERS
    last = periods[-1]
    out: dict[Key, dict] = {}

    def put(name, period, formula, *inputs):
        out[(name, period)] = {"formula": formula, "inputs": list(inputs)}

    # history = seed quarters + forecast quarters; ttm[i] = history[i + 1 : i + 5] (quarters)
    history = [_row(dcf.SEED, p) for p in seed] + [_out("revenue", p) for p in periods[:q]]
    ttm = [history[i + 1 : i + 5] for i in range(q)] + [[_out("revenue", p)] for p in periods[q:]]
    for i, p in enumerate(periods):
        growth = _row("revenue_growth", p)
        if i < q:
            base = _row(dcf.SEED, seed[i]) if i < 4 else _out("revenue", periods[i - 4])
            put("revenue", p, "revenue_from_growth_vs_year_earlier", base, growth)
        elif i == q:
            put(
                "revenue",
                p,
                "revenue_year_from_last_four_quarters",
                *(_out("revenue", x) for x in periods[q - 4 : q]),
                growth,
            )
        else:
            put("revenue", p, "revenue_from_growth", _out("revenue", periods[i - 1]), growth)
        put("ebit", p, "revenue_times_margin", _out("revenue", p), _row("operating_margin", p))
        put("d_and_a", p, "revenue_times_da_share", _out("revenue", p), _row("da_pct", p))
        put("capex", p, "revenue_times_capex_share", _out("revenue", p), _row("capex_pct", p))
        put("nopat", p, "ebit_after_tax", _out("ebit", p), _row("tax_rate", p))
        if i == 0:
            # share × (trailing revenue − the seed year) with one share: the three seed quarters
            # in both cancel, leaving this quarter's revenue and the seed quarter it replaces
            put(
                "delta_nwc",
                p,
                "first_change_in_working_capital",
                _row("nwc_pct", p),
                _out("revenue", p),
                _row(dcf.SEED, seed[0]),
            )
        else:
            before = [_row("nwc_pct", periods[i - 1]), *ttm[i - 1]]
            put("delta_nwc", p, "change_in_working_capital", _row("nwc_pct", p), *ttm[i], *before)
        put(
            "fcff",
            p,
            "fcff",
            _out("ebit", p),
            _row("tax_rate", p),
            _out("d_and_a", p),
            _out("capex", p),
            _out("delta_nwc", p),
        )
        previous = [_out("discount_factor", periods[i - 1])] if i else []
        put("discount_factor", p, "discount_factor", _out("wacc", SINGLE_PERIOD), *previous)

    one = SINGLE_PERIOD
    wacc_set = dcf.wacc_is_set(rows)
    put("cost_of_equity", one, "capm", _row("risk_free", one), _row("beta", one), _row("erp", one))
    if wacc_set:  # a what-if that sets the rate itself (backlog #171)
        put("wacc", one, "wacc_set_directly", _row(dcf.WACC_SET, one))
    else:
        put(
            "wacc",
            one,
            "wacc",
            _out("cost_of_equity", one),
            _row("equity_market_value", one),
            _row("debt", one),
            _row("cost_of_debt", one),
            _row("debt_tax_rate", one),
        )
    put(
        "pv_explicit",
        one,
        "present_value_of_cash_flows",
        *(x for p in periods for x in (_out("fcff", p), _out("discount_factor", p))),
    )
    method = [_row("terminal_method", one)] if "terminal_method" in index else []
    if dcf.terminal_method(rows) == dcf.VALUE_DRIVER:
        tv = ("value_driver_terminal_value", _out("nopat", last))
    else:
        tv = ("gordon_terminal_value", _out("fcff", last))
    put(
        "terminal_value",
        one,
        tv[0],
        tv[1],
        _out("wacc", one),
        _row("terminal_growth", one),
        *method,
    )
    put(
        "pv_terminal",
        one,
        "discounted_terminal_value",
        _out("terminal_value", one),
        _out("discount_factor", last),
    )
    put(
        "enterprise_value",
        one,
        "sum_of_present_values",
        _out("pv_explicit", one),
        _out("pv_terminal", one),
    )
    put(
        "terminal_share",
        one,
        "terminal_share",
        _out("pv_terminal", one),
        _out("enterprise_value", one),
    )
    put(
        "enterprise_value_as_of",
        one,
        "rolled_forward",
        _out("enterprise_value", one),
        _out("wacc", one),
        _row("roll_years", one),
    )
    put("net_debt", one, "net_debt", _row("debt", one), _row("cash_and_investments", one))
    put(
        "equity_value",
        one,
        "equity_value",
        _out("enterprise_value_as_of", one),
        _out("net_debt", one),
        _row("minority_interest", one),
    )
    put("value_per_share", one, "per_share", _out("equity_value", one), _row("shares", one))
    for side in () if wacc_set else ("minus", "plus"):  # not computed with WACC set
        put(
            f"value_per_share_erp_{side}_1se",
            one,
            f"revalued_at_erp_{side}_1se",
            _out("value_per_share", one),
            _row("erp", one),
            _row("erp_std_error", one),
        )
    return out


def reaches(trace: dict[Key, dict], output: Key) -> set[Key]:
    """Every row an output is computed from, following outputs back to rows."""
    seen_outputs: set[Key] = set()
    found: set[Key] = set()
    stack = [output]
    while stack:
        key = stack.pop()
        if key in seen_outputs:
            continue
        seen_outputs.add(key)
        for ref in trace[key]["inputs"]:
            if ref["of"] == "row":
                found.add((ref["name"], ref["period"]))
            else:
                stack.append((ref["name"], ref["period"]))
    return found


# -- what the app reads (item 4) -------------------------------------------------------------------

FRED_URL = "https://fred.stlouisfed.org/series/{series}"
YAHOO_URL = "https://finance.yahoo.com/quote/{series}/history"


@dataclass(frozen=True)
class RunSources:
    run_id: str
    parent_run_id: str | None
    ticker: str
    as_of: str  # the fecha de corte: nothing behind the run was public after it
    recorded: bool
    rows: list[dict]
    outputs: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def _filing(f) -> dict:
    """The #140 Filing shape, with its date as ISO text."""
    out = asdict(f)
    out["filed_at"] = f.filed_at.isoformat() if f.filed_at else None
    return out


def run_sources(conn: sqlite3.Connection, run_id: str) -> RunSources:
    """Every row of a stored run with its sources, filings with form, date and EDGAR link and
    market series with the download the run used; and every output with its formula and inputs.
    Reads only the run's stored rows and, by accession, the filings behind them."""
    from domains.analysis.reported import _Filings
    from domains.analysis.runs import load_assumptions, load_gaps, load_outputs

    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise SourceError(f"no run {run_id}")
    rows = load_assumptions(conn, run_id)
    stored = load(conn, run_id)
    filings = _Filings(conn, run["cik"])
    fetches = {
        run["ticker"]: run["price_fetch_sha256"],
        MARKET_INDEX: run["index_fetch_sha256"],
        RISK_FREE_SERIES: run["yield_fetch_sha256"],
    }

    def shown(item: dict) -> dict:
        item = dict(item)
        if item["kind"] == "filing":
            accession = item["accession_no"]
            item["filing"] = _filing(filings.get(accession)) if accession else None
            item["input_filings"] = [_filing(filings.get(a)) for a in item["inputs"]]
        elif item["kind"] == "market":
            item["label"] = PROVIDERS[item["provider"]]
            item["fetch_sha256"] = fetches.get(item["series"])
            url = FRED_URL if item["provider"] == "fred" else YAHOO_URL
            item["url"] = url.format(series=quote(item["series"]))
        elif item["kind"] == "rule":
            item["text"] = RULES[item["code"]]
        elif item["kind"] == "what_if":
            item["parent_sources"] = [shown(i) for i in item["parent_sources"]]
        return item

    out_rows = []
    for a in rows:
        items = stored.get((a.name, a.period), [])
        out_rows.append(
            {
                "name": a.name,
                "period": a.period,
                "value": a.value,
                "sources": [shown(i) for i in items],
                "gap": None if items else NOT_RECORDED,
            }
        )
    values = load_outputs(conn, run_id)
    gaps = load_gaps(conn, run_id)
    outputs = []
    for key, step in sorted(output_trace(rows).items()):
        if key not in values and key not in gaps:
            continue
        gap = gaps.get(key)
        outputs.append(
            {
                "name": key[0],
                "period": key[1],
                "value": values.get(key),
                "formula": step["formula"],
                "inputs": step["inputs"],
                "no_value": None if gap is None else {"code": gap.reason},
            }
        )
    return RunSources(
        run_id=run_id,
        parent_run_id=run["parent_run_id"],
        ticker=run["ticker"],
        as_of=run["as_of"],
        recorded=bool(stored),
        rows=out_rows,
        outputs=outputs,
    )


# -- older runs (item 5) ---------------------------------------------------------------------------

BACKFILL = ("filled", "already_recorded", "what_if_not_backfilled", "rebuild_differs", "failed")


def backfill(conn: sqlite3.Connection, run_id: str, today: date | None = None) -> tuple[str, str]:
    """Give a baseline stored before this version its sources: rebuild its rows from its pinned
    data (M2.1) and store the rebuilt sources only when every rebuilt row equals the stored one,
    value and method. Returns (status, detail), status one of BACKFILL; stores nothing otherwise."""
    from domains.analysis.runs import load_assumptions, rebuild, write_lock
    from domains.market.store import MarketDataError

    run = conn.execute("SELECT parent_run_id FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise SourceError(f"no run {run_id}")
    if load(conn, run_id):
        return "already_recorded", ""
    if run["parent_run_id"] is not None:
        return "what_if_not_backfilled", f"a what-if of {run['parent_run_id']}"
    try:
        built = rebuild(conn, run_id, today=today)
        if built.ok:
            check(load_assumptions(conn, run_id), built.sources)
    except (ValueError, MarketDataError) as e:  # SourceError is a ValueError
        return "failed", str(e)
    if not built.ok:
        first = ", ".join(" ".join(m) for m in built.mismatches[:3])
        return "rebuild_differs", f"{len(built.mismatches)} rows differ ({first})"
    with write_lock(conn):
        if load(conn, run_id):  # another writer filled it meanwhile
            return "already_recorded", ""
        insert(conn, run_id, built.sources)
    return "filled", ""
