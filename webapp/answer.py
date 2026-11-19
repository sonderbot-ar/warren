"""The first screen's answer: brief Q5, a company's revenue for the next four quarters and how
sure that forecast is (F2 Step 4b, `docs/designs/f2-web-app.md`; mockup approved nov.18.2026).

Two halves, kept apart so the second can be tested without a database:

- `load_bundle(conn, ticker, corte)` makes the engine's calls, as a library, and keeps only what
  the screen shows: the stored baseline run of that company dated the *fecha de corte*, its
  ranges and their track record (`run_ranges`), its sources (`run_sources`) and the inputs its
  four revenue figures reach (`inputs_behind`). Plain JSON types, so a test can store one.
- `answer_view(bundle, region, t)` turns the bundle into what the template draws: labels,
  figures formatted for the student's region, the chart's geometry and, for each figure a
  student can open, what its *Fuente* tab says. It computes no financial number: every value
  is the engine's, and the app only rounds it for display and places it on the chart.
"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from webapp import formatting

QUARTERS_SHOWN = 4  # brief Q5: the next four quarters
POOL = "pooled"  # the range the brief shows: every company's past misses (M9's headline)
HISTORY_QUARTERS = 8  # reported quarters on the chart, before the forecast
GROWTH = "revenue_growth"
SEED = "revenue_seed"


class NoRun(LookupError):
    """No stored baseline run of this company is dated the fecha de corte."""


# -- the engine's calls --------------------------------------------------------------------------


def find_run(conn: sqlite3.Connection, ticker: str, corte: date) -> str | None:
    """The newest stored baseline of `ticker` dated `corte`: not a what-if (no parent), not a
    simulation (no seed), and with no assumption an LLM proposed. None when there is none."""
    row = conn.execute(
        """
        SELECT r.run_id FROM runs r
        WHERE r.ticker = ? AND r.as_of = ? AND r.parent_run_id IS NULL AND r.seed IS NULL
          AND NOT EXISTS (SELECT 1 FROM assumptions a
                          WHERE a.run_id = r.run_id AND a.source = 'llm_proposed')
        ORDER BY r.created_at DESC, r.run_id DESC LIMIT 1
        """,
        (ticker.upper(), corte.isoformat()),
    ).fetchone()
    return None if row is None else row[0]


def load_bundle(conn: sqlite3.Connection, ticker: str, corte: date) -> dict:
    """Everything the answer shows, from the engine. Raises NoRun when nothing is stored."""
    run_id = find_run(conn, ticker, corte)
    if run_id is None:
        raise NoRun(f"{ticker} {corte}")
    return bundle_for_run(conn, run_id)


def bundle_for_run(conn: sqlite3.Connection, run_id: str) -> dict:
    """The answer's bundle for one stored run. A stored run never changes (its rows, outputs
    and sources are written once), so the app may keep this per run_id: the engine's calls take
    about ten seconds, and every figure the student opens would otherwise repeat them."""
    from domains.analysis.inputs import inputs_behind
    from domains.analysis.sources import run_sources
    from domains.evaluation.run_ranges import run_ranges

    company = conn.execute(
        "SELECT c.ticker, c.name, c.fiscal_year_end FROM runs r "
        "JOIN companies c ON c.cik = r.cik WHERE r.run_id = ?",
        (run_id,),
    ).fetchone()
    ranges = run_ranges(conn, run_id).to_dict()
    quarters = ranges["quarters"][:QUARTERS_SHOWN]
    outputs = [("revenue", q["period"]) for q in quarters]
    inputs = inputs_behind(conn, run_id, outputs).to_dict()
    sources = run_sources(conn, run_id).to_dict()
    wanted_rows = {(c["name"], r["period"]) for c in inputs["cells"] for r in c["rows"]}
    wanted_outputs = set(outputs)
    return {
        "run_id": run_id,
        "as_of": ranges["as_of"],
        "company": {
            "ticker": company["ticker"],
            "name": company["name"],
            "fiscal_year_end": company["fiscal_year_end"],
        },
        "ranges": {
            "errors_filed_to": ranges["errors_filed_to"],
            "quarters": [
                {
                    "period": q["period"],
                    "revenue_forecast": q["revenue_forecast"],
                    "band": next(
                        (
                            {"n_errors": b["n_errors"], "revenue": b["revenue"]}
                            for b in q["bands"]
                            if b["pool"] == POOL
                        ),
                        None,
                    ),  # fmt: skip
                }
                for q in quarters
            ],
            "coverage": [
                c for c in ranges["coverage"] if c["pool"] == POOL and c["item"] == "revenue"
            ],
        },
        "sources": {
            "outputs": [
                o for o in sources["outputs"] if (o["name"], o["period"]) in wanted_outputs
            ],
            "rows": [r for r in sources["rows"] if (r["name"], r["period"]) in wanted_rows],
        },
        "inputs": inputs,
    }


# -- labels --------------------------------------------------------------------------------------


def _parse_period(label: str) -> tuple[int, int]:
    """FY2026Q4 -> (2026, 4)."""
    year, quarter = label.removeprefix("FY").split("Q")
    return int(year), int(quarter)


def fiscal_end_month(fiscal_year_end: str | None) -> int:
    """The month a fiscal year ends, from SEC's MMDD. A year that ends in the first week of a
    month (Johnson & Johnson's 0103: a 52- or 53-week year) is the previous month's year."""
    if not fiscal_year_end:
        return 12
    month, day = int(fiscal_year_end[:2]), int(fiscal_year_end[2:])
    if day <= 7:
        month = 12 if month == 1 else month - 1
    return month


def quarter_months(label: str, fiscal_year_end: str | None) -> tuple[date, date]:
    """The first and last calendar month (as their first day) of a fiscal quarter. For Apple
    (year ends in September) FY2026Q4 is July to September 2026 and FY2027Q1 October to
    December 2026. Calendar months only: a 13-week quarter ends near, not at, a month's end."""
    year, quarter = _parse_period(label)
    end = fiscal_end_month(fiscal_year_end)
    months = []
    for k in range(3):
        offset = end + 3 * (quarter - 1) + k + 1  # months after the previous fiscal year's end
        m = (offset - 1) % 12 + 1
        y = year - 1 + (offset - 1) // 12
        months.append(date(y, m, 1))
    return months[0], months[-1]


def quarter_closed(label: str, fiscal_year_end: str | None, corte: date) -> bool:
    _, last = quarter_months(label, fiscal_year_end)
    return date(last.year, last.month, calendar.monthrange(last.year, last.month)[1]) < corte


# -- the view ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Figure:
    """A figure a student can open (design principle 2): its id in the address, its text and
    what the panel's *Fuente* tab shows for it."""

    id: str
    text: str
    title: str  # the panel's heading
    fuente: dict  # what `_fuente.html` draws, by kind
    formula: str | None = None  # the formula bar's text while this figure is open


@dataclass(frozen=True)
class Row:
    period: str
    quarter: str  # "T4 2026"
    months: str  # "jul–sep 2026"
    closed: bool  # the quarter has ended but is not reported yet
    forecast: Figure
    p10: Figure | None
    p90: Figure | None


@dataclass
class AnswerView:
    run_id: str
    ticker: str
    company: str
    as_of: date
    rows: list[Row]
    coverage_all: Figure | None
    coverage_company: Figure | None
    coverage_counts: dict
    chart: dict
    figures: dict[str, Figure] = field(default_factory=dict)


SHORT_NAMES = {  # the companies as a student says them; SEC's names are in capitals
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "WMT": "Walmart",
    "KO": "Coca-Cola",
    "PG": "Procter & Gamble",
    "JNJ": "Johnson & Johnson",
    "CAT": "Caterpillar",
    "XOM": "Exxon Mobil",
}


def _month_span(first: date, last: date, region: formatting.Region) -> str:
    a = formatting.format_month(first, region)
    b = formatting.format_month(last, region)
    if first.year == last.year:
        return f"{a}–{b} {last.year}"
    return f"{a} {first.year}–{b} {last.year}"


def answer_view(bundle: dict, region: formatting.Region, t) -> AnswerView:
    company = bundle["company"]
    ticker, fye = company["ticker"], company["fiscal_year_end"]
    name = SHORT_NAMES.get(ticker, company["name"])
    as_of = date.fromisoformat(bundle["as_of"])
    millions = lambda v: formatting.figure(v, "millions", region)  # noqa: E731
    percent = lambda v: formatting.figure(v, "percent", region) + "%"  # noqa: E731
    as_of_text = formatting.format_date(as_of, region)

    def qlabel(period: str) -> str:
        year, q = _parse_period(period)
        return t("answer.quarter", q=q, year=year)

    rows_by_key = {(r["name"], r["period"]): r for r in bundle["sources"]["rows"]}
    outputs_by_period = {o["period"]: o for o in bundle["sources"]["outputs"]}
    cells = {c["name"]: c for c in bundle["inputs"]["cells"]}
    growth_years = _growth_years(cells.get(GROWTH))

    figures: dict[str, Figure] = {}
    rows = []
    for q in bundle["ranges"]["quarters"]:
        period = q["period"]
        first, last = quarter_months(period, fye)
        months = _month_span(first, last, region)
        out = outputs_by_period.get(period)
        seed_key = next((i["name"], i["period"]) for i in out["inputs"] if i["name"] == SEED)
        growth_key = next((i["name"], i["period"]) for i in out["inputs"] if i["name"] == GROWTH)
        seed, growth = rows_by_key[seed_key], rows_by_key[growth_key]
        fid = f"pronostico-{period}"
        figures[fid] = Figure(
            fid,
            millions(q["revenue_forecast"]),
            t("answer.panel.forecast_title", quarter=qlabel(period)),
            {
                "kind": "forecast",
                "lead": t("answer.fuente.forecast_lead", quarter=qlabel(period), months=months),
                "value": millions(q["revenue_forecast"]),
                "how": t("formula." + out["formula"]),
                "run_line": t(
                    "answer.fuente.run_line", date=as_of_text, run_id=bundle["run_id"], company=name
                ),  # fmt: skip
                "items": [_seed_item(seed, qlabel, millions, region, t)]
                + _growth_items(growth, growth_years, millions, percent, region, t),
                "foot": t("answer.fuente.same_filing") + " " + t("answer.fuente.rounding"),
            },
            t(
                "answer.fx.forecast",
                formula=formatting.spreadsheet_product(seed["value"], growth["value"], region),
                seed=millions(seed["value"]),
                growth=percent(growth["value"]),
            ),
        )
        p10 = p90 = None
        band = q["band"]
        if band and band["revenue"]:
            for end in ("p10", "p90"):
                eid = f"{end}-{period}"
                figures[eid] = Figure(
                    eid,
                    millions(band["revenue"][end]),
                    t(f"answer.panel.{end}_title", quarter=qlabel(period)),
                    {
                        "kind": "range",
                        "lead": t(f"answer.fuente.{end}_lead", quarter=qlabel(period),
                                  months=months),  # fmt: skip
                        "value": millions(band["revenue"][end]),
                        "how": t("answer.fuente.range_how", n=formatting.count(band["n_errors"],
                                                                                region)),
                        "run_line": t("answer.fuente.range_known", date=as_of_text,
                                      filed_to=formatting.format_date(
                                          date.fromisoformat(bundle["ranges"]["errors_filed_to"]),
                                          region)),
                        "items": [],
                        "foot": t("answer.fuente.range_foot"),
                    },
                )  # fmt: skip
            p10, p90 = figures[f"p10-{period}"], figures[f"p90-{period}"]
        rows.append(
            Row(period, qlabel(period), months, quarter_closed(period, fye, as_of),
                figures[fid], p10, p90)
        )  # fmt: skip

    coverage = {c["scope"]: c for c in bundle["ranges"]["coverage"]}
    cov_figs = {}
    for scope in ("all", "company"):
        c = coverage.get(scope)
        if c is None or c["share"] is None:
            cov_figs[scope] = None
            continue
        cid = f"cobertura-{scope}"
        figures[cid] = cov_figs[scope] = Figure(
            cid,
            percent(c["share"]),
            t(f"answer.panel.coverage_{scope}_title", company=name),
            {
                "kind": "coverage",
                "lead": t(f"answer.coverage.{scope}", company=name),
                "value": percent(c["share"]),
                "how": t("answer.fuente.coverage_how",
                         inside=formatting.count(c["inside"], region),
                         n=formatting.count(c["n"], region),
                         below=formatting.count(c["below"], region),
                         above=formatting.count(c["above"], region)),
                "run_line": t("answer.fuente.coverage_interval",
                              low=percent(c["interval"][0]), high=percent(c["interval"][1])),
                "items": [],
                "foot": t("answer.fuente.coverage_foot",
                          since=formatting.format_date(date.fromisoformat(c["origins_from"]),
                                                       region)),
            },
        )  # fmt: skip
    counts = {
        scope: {
            "inside": formatting.count(coverage[scope]["inside"], region),
            "n": formatting.count(coverage[scope]["n"], region),
        }
        for scope in coverage
    }
    view = AnswerView(
        bundle["run_id"], ticker, name, as_of, rows, cov_figs.get("all"),
        cov_figs.get("company"), counts, _chart(bundle, region, t, qlabel), figures,
    )  # fmt: skip
    return view


def _growth_years(cell: dict | None) -> dict[str, dict]:
    """The same-filing annual growth points the growth assumption was computed from."""
    if cell is None:
        return {}
    for series in cell["history"]:
        if series["primary"] and series["frequency"] == "year":
            return {p["period"]: p for p in series["points"]}
    return {}


def _filing_text(f: dict, region, t, short: bool = False) -> str:
    key = "answer.fuente.filing_short" if short else "answer.fuente.filing"
    return t(key, form=f["form"], accession=f["accession_no"],
             date=formatting.format_date(date.fromisoformat(f["filed_at"]), region))  # fmt: skip


def _seed_item(seed: dict, qlabel, millions, region, t) -> dict:
    src = seed["sources"][0] if seed["sources"] else None
    label = t("answer.fuente.seed_label", quarter=qlabel(seed["period"]),
              value=millions(seed["value"]))  # fmt: skip
    if src is None:
        return {"cell": "B", "label": label, "meta": t("answer.fuente.not_recorded"), "links": []}
    if src["derived"]:
        filings = src["input_filings"]
        how = t("answer.fuente.derived_q4") if src["fiscal_period"] == "Q4" else ""
        listed = t("answer.fuente.and").join(_filing_text(f, region, t, short=True)
                                             for f in filings)  # fmt: skip
        meta = f"{how} · {listed}" if how else listed
        return {"cell": "B", "label": label, "meta": meta,
                "links": [(f["form"], f["url"]) for f in filings]}  # fmt: skip
    f = src["filing"]
    return {"cell": "B", "label": label, "meta": _filing_text(f, region, t),
            "links": [(f["form"], f["url"])]}  # fmt: skip


def _growth_items(growth: dict, years: dict, millions, percent, region, t) -> list[dict]:
    """One line per fiscal year the growth assumption averaged, newest first: the two years'
    revenue as one 10-K reports them and the growth between them (both from the engine)."""
    items = []
    used = sorted((p for p in years.values() if p["used"]), key=lambda p: p["period"],
                  reverse=True)  # fmt: skip
    for point in used:
        year = int(point["period"].removeprefix("FY"))
        parts = sorted(point["parts"], key=lambda part: part["period"], reverse=True)
        values = t("answer.fuente.and").join(millions(part["value"]) for part in parts)
        filing = next((p["filing"] for p in parts if p["filing"]), None)
        items.append({
            "cell": "C",
            "label": t("answer.fuente.growth_label", year=year, prior=year - 1, values=values,
                       growth=percent(point["value"])),
            "meta": _filing_text(filing, region, t) if filing else "",
            "links": [(filing["form"], filing["url"])] if filing else [],
        })  # fmt: skip
    if not items:
        items.append({"cell": "C", "label": t("answer.fuente.growth_value",
                                              value=percent(growth["value"])),
                      "meta": t("answer.fuente.not_recorded"), "links": []})  # fmt: skip
    return items


# -- the chart -----------------------------------------------------------------------------------

# The plot area of each drawing, in viewBox units: the laptop's and the phone's. The phone's is
# narrower in units, so the same type size reads larger once the drawing is scaled to 390 px.
LAYOUTS = {
    "l": {"box": "-28 0 508 300", "left": 56, "right": 468, "top": 30, "bottom": 260,
          "label_every": 2, "label_from": 1, "xlab_y": 278},
    "s": {"box": "0 0 380 270", "left": 72, "right": 372, "top": 30, "bottom": 230,
          "label_every": 4, "label_from": 0, "xlab_y": 248},
}  # fmt: skip


def _nice_step(span: float) -> float:
    raw = span / 5
    magnitude = 10 ** (len(str(int(raw))) - 1)
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * magnitude:
            return m * magnitude
    return 10 * magnitude


def _chart(bundle: dict, region, t, qlabel) -> dict:
    """Where the reported quarters, the forecast and its p10–p90 band sit on the chart, for the
    laptop's drawing ("l") and the phone's ("s"). Only placement: the values are the engine's
    (reported revenue from `inputs_behind`, the forecast and band from `run_ranges`)."""
    seed = next((c for c in bundle["inputs"]["cells"] if c["name"] == SEED), None)
    reported = []
    if seed is not None:
        for series in seed["history"]:
            for p in series["points"]:
                if p["value"] is not None:
                    reported.append((p["period_end"], p["period"], p["value"]))
    reported = [(per, v) for _, per, v in sorted(reported)[-HISTORY_QUARTERS:]]
    forecast = [
        (q["period"], q["revenue_forecast"], (q["band"] or {}).get("revenue"))
        for q in bundle["ranges"]["quarters"]
    ]
    values = [v for _, v in reported] + [v for _, v, _ in forecast]
    values += [b[k] for _, _, b in forecast if b for k in ("p10", "p90")]
    step = _nice_step((max(values) - min(values)) / 1e6) * 1e6
    low = (min(values) // step) * step
    high = -(-max(values) // step) * step

    def short(period: str) -> str:
        year, q = _parse_period(period)
        return t("answer.quarter_short", q=q, yy=f"{year % 100:02d}")

    labels = [short(per) for per, _ in reported] + [short(per) for per, _, _ in forecast]
    company = SHORT_NAMES.get(bundle["company"]["ticker"], bundle["company"]["name"])
    out = {"aria": t("answer.chart.aria", company=company, reported=len(reported),
                     forecast=len(forecast))}  # fmt: skip
    for name, lay in LAYOUTS.items():
        left, right, top, bottom = lay["left"], lay["right"], lay["top"], lay["bottom"]
        dx = (right - left) / (len(reported) + len(forecast))

        def x(i: int, left=left, dx=dx) -> float:
            return round(left + dx * (i + 0.5), 1)

        def y(v: float, top=top, bottom=bottom) -> float:
            return round(bottom - (v - low) / (high - low) * (bottom - top), 1)

        ticks, v = [], low
        while v <= high + 1:
            ticks.append({"y": y(v), "label": formatting.figure(v, "millions", region)})
            v += step
        actual = [(x(i), y(v)) for i, (_, v) in enumerate(reported)]
        k = len(reported)
        fc = [(x(k + i), y(v)) for i, (_, v, _) in enumerate(forecast)]
        upper = [(x(k + i), y(b["p90"])) for i, (_, _, b) in enumerate(forecast) if b]
        lower = [(x(k + i), y(b["p10"])) for i, (_, _, b) in enumerate(forecast) if b]
        out[name] = {
            **lay,
            "ticks": ticks,
            "xlabels": [{"x": x(i), "label": label} for i, label in enumerate(labels)
                        if i % lay["label_every"] == lay["label_from"]],
            "split_x": round(left + dx * k, 1),
            "actual": actual,
            "forecast": actual[-1:] + fc,
            "forecast_dots": fc,
            "band": actual[-1:] + upper + lower[::-1] if upper else [],
            "whiskers": [(a[0], a[1], b[1]) for a, b in zip(lower, upper, strict=True)],
        }  # fmt: skip
    return out
