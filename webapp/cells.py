"""The cells behind the answer (F2 Step 4b part 2; input-charts Step 1,
`docs/designs/f2-input-charts.md`; mockup approved by the owner nov.19.2026).

For each assumption row the answer's four revenue figures reach, one card: how that cell moved
over past years and what Warren assumes now, drawn so the two are easy to compare, with the
figures as a table under "Ver los datos de las gráficas". Everything comes from the engine's
`inputs_behind` (fetched once at ten years, `answer.HISTORY_YEARS_MAX`); the view keeps the last
`years` of it (3, 5 or 10, the screen's switch) and places the engine's values on the drawing.
It computes no financial number.

Two kinds of card today, the two a revenue answer reaches:

- **seed** (`revenue_seed`, cell B): one small chart per fiscal quarter, that quarter in each
  past year, the base (the seed) and the forecast it leads to. Small multiples, because the
  rule compares a quarter with the same quarter a year earlier.
- **ratio** (`revenue_growth`, cell C): annual growth by fiscal year, the averaged years in the
  accent colour and the assumption as a dashed bar; then quarterly growth against the same
  quarter a year earlier, with the assumption as a dashed line across it.

Any other cell gets a plain card with its values, until a screen that reaches it designs one.
"""

from __future__ import annotations

import math
from datetime import date

from webapp import formatting

YEARS_OPTIONS = (3, 5, 10)
DEFAULT_YEARS = 5  # the owner's choice on the input-charts card, nov.19.2026
SEED = "revenue_seed"
GROWTH = "revenue_growth"
LETTERS = {SEED: "B", GROWTH: "C"}  # the formula bar's letters: forecast = B × (1 + C)

# Drawing sizes in viewBox units, laptop ("l") and phone ("s"), as the approved mockup has them.
MINI = {
    "l": {"box": "0 0 260 150", "left": 10, "right": 248, "top": 8, "bottom": 114.7, "xlab_y": 146,
          "width": 260},
    "s": {"box": "0 0 140 118", "left": 10, "right": 128, "top": 8, "bottom": 86.2, "xlab_y": 114,
          "width": 140},
}  # fmt: skip
ANNUAL = {
    "l": {"box": "0 0 600 236", "left": 44, "right": 592, "top": 26, "bottom": 186, "xlab_y": 208},
    "s": {"box": "0 0 320 236", "left": 44, "right": 312, "top": 26, "bottom": 186, "xlab_y": 208},
}  # fmt: skip
QUARTERLY = {
    "l": {"box": "0 0 600 210", "left": 44, "right": 592, "top": 18, "bottom": 186, "xlab_y": 204,
          "label_width": 60},
    "s": {"box": "0 0 320 210", "left": 44, "right": 312, "top": 18, "bottom": 186, "xlab_y": 204,
          "label_width": 58},
}  # fmt: skip
VALUE_LABEL_MIN_SLOT = 44  # a bar's value is written above it only when its slot is this wide


def years_from(raw: str | None) -> int:
    """The address's `anos`, or the default for anything that is not one of the options."""
    try:
        years = int(raw or "")
    except ValueError:
        return DEFAULT_YEARS
    return years if years in YEARS_OPTIONS else DEFAULT_YEARS


def _nice_step(span: float, parts: int) -> float:
    """A round step (1, 2, 2.5 or 5 times a power of ten) that cuts `span` into about `parts`."""
    raw = span / parts if span > 0 else 1.0
    magnitude = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * magnitude + 1e-12:
            return m * magnitude
    return 10 * magnitude


def _scale(values: list[float], parts: int, include_zero: bool) -> tuple[float, float, float]:
    low, high = min(values), max(values)
    if include_zero:
        low, high = min(low, 0.0), max(high, 0.0)
    step = _nice_step(high - low, parts)
    low = (low // step) * step
    high = -(-high // step) * step
    if high == low:
        high = low + step
    return low, high, step


def _ticks(low: float, high: float, step: float) -> list[float]:
    out, k = [], 0
    while low + k * step <= high + step * 1e-9:
        out.append(round(low + k * step, 12))
        k += 1
    return out


class CellsBuilder:
    """Builds the cards and registers a figure (a door to the side panel) for every value."""

    def __init__(self, bundle: dict, region, t, years: int, ctx: dict):
        self.bundle, self.region, self.t, self.years = bundle, region, t, years
        self.qlabel = ctx["qlabel"]
        self.months = ctx["months"]  # period -> "jul–sep 2026"
        self.figures = ctx["figures"]  # shared with the answer: every id is unique
        self.figure_cls = ctx["figure_cls"]
        self.company = ctx["company"]
        self.as_of_text = ctx["as_of_text"]
        self.forecast_by_seed = ctx["forecast_by_seed"]  # seed period -> {id, value, period}
        self.growth_items = ctx["growth_items"]  # the Fuente lines for the growth assumption

    # -- formatting ------------------------------------------------------------------------------

    def millions(self, v: float) -> str:
        return formatting.figure(v, "millions", self.region)

    def percent(self, v: float) -> str:
        return formatting.figure(v, "percent", self.region) + "%"

    def tick_percent(self, v: float, step: float) -> str:
        """An axis label: whole percents when the step is whole ("−10%"), else one decimal."""
        if round(step * 100, 9) == round(step * 100):
            return formatting.figure(v * 1e8, "millions", self.region) + "%"
        return self.percent(v)

    def listing(self, items: list[str]) -> str:
        """ "a, b y c" in the region's language."""
        if len(items) < 2:
            return "".join(items)
        return ", ".join(items[:-1]) + self.t("answer.fuente.and") + items[-1]

    def period_label(self, period: str) -> str:
        if "Q" in period:
            return self.qlabel(period)
        return self.t("cells.fiscal_year", year=period.removeprefix("FY"))

    def short_label(self, period: str) -> str:
        year, quarter = period.removeprefix("FY").split("Q")
        return self.t("answer.quarter_short", q=quarter, yy=f"{int(year) % 100:02d}")

    def filing_text(self, f: dict) -> str:
        return self.t("answer.fuente.filing", form=f["form"],
                      accession=f["accession_no"].replace("-", "‑"),
                      date=formatting.format_date(date.fromisoformat(f["filed_at"]),
                                                  self.region))  # fmt: skip

    # -- figures ---------------------------------------------------------------------------------

    def part_filings(self, part: dict) -> list[dict]:
        if part.get("filing"):
            return [part["filing"]]
        return list(part.get("inputs") or [])

    def revenue_figure(self, part: dict, letter: str) -> str:
        """The door for one reported revenue figure (a quarter, or a fiscal year)."""
        period = part["period"]
        fid = f"ingresos-{period}"
        if fid in self.figures:
            return fid
        filings = self.part_filings(part)
        if part.get("derived"):
            how = self.t("answer.fuente.derived_q4")
        else:
            how = self.t("cells.fuente.reported_in", form=filings[0]["form"] if filings else "")
        lead_key = "cells.fuente.revenue_quarter" if "Q" in period else "cells.fuente.revenue_year"
        self.figures[fid] = self.figure_cls(
            fid,
            self.millions(part["value"]),
            self.t("cells.panel.revenue_title", period=self.period_label(period)),
            {
                "kind": "history",
                "lead": self.t(lead_key, period=self.period_label(period),
                               months=self.months.get(period, ""), company=self.company),
                "value": self.millions(part["value"]),
                "how": how,
                "run_line": self.t("cells.fuente.known_on", date=self.as_of_text),
                "items": [{"cell": letter, "label": self.filing_text(f), "meta": "",
                           "links": [(f["form"], f["url"])]} for f in filings],
                "foot": self.t("cells.fuente.history_foot"),
            },
            self.t("cells.fx.derived" if part.get("derived") else "cells.fx.reported"),
        )  # fmt: skip
        return fid

    def growth_figure(self, point: dict, letter: str) -> str:
        """The door for one growth rate: the period's revenue against a year earlier."""
        period = point["period"]
        fid = f"crecimiento-{period}"
        if fid in self.figures:
            return fid
        now = next(p for p in point["parts"] if p["period"] == point["period"])
        before = next(p for p in point["parts"] if p["period"] != point["period"])
        lead_key = "cells.fuente.growth_quarter" if "Q" in period else "cells.fuente.growth_year"
        items = []
        for part in (now, before):
            for f in self.part_filings(part):
                items.append({
                    "cell": letter,
                    "label": self.t("answer.fuente.seed_label",
                                    quarter=self.period_label(part["period"]),
                                    value=self.millions(part["value"])),
                    "meta": self.filing_text(f),
                    "links": [(f["form"], f["url"])],
                })  # fmt: skip
        formula = "={}/{}-1".format(
            formatting.spreadsheet_number(now["value"] / 1e6, 0, self.region),
            formatting.spreadsheet_number(before["value"] / 1e6, 0, self.region),
        )
        self.figures[fid] = self.figure_cls(
            fid,
            self.percent(point["value"]),
            self.t("cells.panel.growth_title", period=self.period_label(period)),
            {
                "kind": "growth",
                "lead": self.t(lead_key, period=self.period_label(period),
                               prior=self.period_label(before["period"])),
                "value": self.percent(point["value"]),
                "how": self.t("cells.fuente.growth_how", now=self.millions(now["value"]),
                              before=self.millions(before["value"])),
                "run_line": self.t("cells.fuente.known_on", date=self.as_of_text),
                "items": items,
                "foot": self.t("cells.fuente.growth_foot"),
            },
            self.t("cells.fx.growth", formula=formula),
        )  # fmt: skip
        return fid

    def assumption_figure(self, cell: dict, reference: dict | None) -> str:
        fid = f"supuesto-{cell['name']}"
        if fid in self.figures:
            return fid
        row = cell["rows"][0]
        used = [p.removeprefix("FY") for p in row["used"]]
        formula = None
        if reference and reference.get("how") == "mean" and reference.get("value") is not None:
            values = [p["value"] for p in self._primary_annual(cell)["points"] if p["used"]]
            formula = self.t(
                "cells.fx.mean",
                formula=formatting.spreadsheet_formula(
                    "AVERAGE",
                    [float(formatting.spreadsheet_number(v, 6, formatting.REGIONS["en-US"])
                           .replace("−", "-")) for v in values],
                    self.region,
                ),
            )  # fmt: skip
        self.figures[fid] = self.figure_cls(
            fid,
            self.percent(row["value"]),
            self.t("cells.panel.assumption_title"),
            {
                "kind": "assumption",
                "lead": self.t("cells.fuente.assumption_lead"),
                "value": self.percent(row["value"]),
                "how": self.t("cells.fuente.assumption_how",
                              years=self.listing(used)),
                "run_line": self.t("answer.fuente.run_line", date=self.as_of_text,
                                   run_id=self.bundle["run_id"], company=self.company),
                "items": self.growth_items,
                "foot": self.t("answer.fuente.same_filing"),
            },
            formula,
        )  # fmt: skip
        return fid

    # -- cards -----------------------------------------------------------------------------------

    def build(self) -> dict:
        cards = []
        for cell in self.bundle["inputs"]["cells"]:
            if cell["name"] == SEED:
                cards.append(self.seed_card(cell))
            elif cell["name"] == GROWTH:
                cards.append(self.ratio_card(cell))
            else:
                cards.append(self.plain_card(cell))
        return {
            "years": self.years,
            "options": YEARS_OPTIONS,
            # "pronóstico = B × (1 + C)." with the letters drawn as the cards' badges
            "formula": [
                (self.t("cells.intro_forecast") + " = ", False),
                ("B", True),
                ("× (1 + ", False),
                ("C", True),
                ("). ", False),
            ],
            "cards": cards,
            "source": self.t("cells.source", date=self.as_of_text, company=self.company),
        }

    def plain_card(self, cell: dict) -> dict:
        return {
            "kind": "plain",
            "letter": LETTERS.get(cell["name"], ""),
            "title": cell["name"],
            "rows": [(self.period_label(r["period"]), r["value"]) for r in cell["rows"]],
        }

    def seed_card(self, cell: dict) -> dict:
        letter = LETTERS[SEED]
        by_quarter = {s["fiscal_quarter"]: s for s in cell["history"]
                      if s["primary"] and s["frequency"] == "quarter"}  # fmt: skip
        minis = []
        for row in cell["rows"]:
            quarter = int(row["period"].split("Q")[1])
            series = by_quarter.get(quarter)
            if series is None:
                continue
            points = [p for p in series["points"] if p["value"] is not None][-self.years :]
            forecast = self.forecast_by_seed.get(row["period"]) or {}
            minis.append({
                "row": row,
                "quarter": quarter,
                "points": points,
                "forecast_id": forecast.get("id"),
                "forecast_value": forecast.get("value"),
                "forecast_period": forecast.get("period"),
            })  # fmt: skip
        values = [p["value"] for m in minis for p in m["points"]]
        values += [m["forecast_value"] for m in minis if m["forecast_value"] is not None]
        low, high, step = _scale(values, 2, include_zero=False)
        mid = (low + high) / 2
        drawn = []
        for m in minis:
            hist = m["points"]
            first_fy, last_fy = hist[0]["fiscal_year"], hist[-1]["fiscal_year"]
            months = self.months.get(m["row"]["period"], "")
            month_span = months.rsplit(" ", 1)[0] if months else ""
            label = self.t("answer.quarter", q=m["quarter"], year="").strip()
            cells_row = []
            for p in hist:
                part = next(x for x in p["parts"] if x["period"] == p["period"])
                cells_row.append({"id": self.revenue_figure(part, letter),
                                  "derived": bool(part.get("derived"))})  # fmt: skip
            base = cells_row[-1]
            aria = self.t(
                "cells.b.aria", quarter=label, n=len(hist),
                low=self.millions(min(p["value"] for p in hist)),
                high=self.millions(max(p["value"] for p in hist)),
                base=self.millions(hist[-1]["value"]),
                forecast=self.millions(m["forecast_value"]) if m["forecast_value"] else "—",
            )  # fmt: skip
            drawings = {}
            for size, lay in MINI.items():
                n = len(hist)
                dx = (lay["right"] - lay["left"]) / n

                def y(v, lay=lay):
                    return round(lay["bottom"] - (v - low) / (high - low)
                                 * (lay["bottom"] - lay["top"]), 1)  # fmt: skip

                pts = [(round(lay["left"] + dx * i, 1), y(p["value"]),
                        self.t("cells.b.point", period=self.qlabel(p["period"]),
                               value=self.millions(p["value"])))
                       for i, p in enumerate(hist)]  # fmt: skip
                fc = None
                if m["forecast_value"] is not None:
                    fc = (lay["right"], y(m["forecast_value"]),
                          self.t("cells.b.forecast_point",
                                 period=self.qlabel(m["forecast_period"]),
                                 value=self.millions(m["forecast_value"])))  # fmt: skip
                drawings[size] = {
                    **lay,
                    "grid": [y(v) for v in (low, mid, high)],
                    "line": [(px, py) for px, py, _ in pts],
                    "history": pts[:-1],
                    "seed": (pts[-1][0], pts[-1][1],
                             self.t("cells.b.seed_point", period=self.qlabel(hist[-1]["period"]),
                                    value=self.millions(hist[-1]["value"]))),
                    "forecast": fc,
                    "first_label": str(first_fy),
                    "last_label": str(first_fy + n) if fc else str(last_fy),
                }  # fmt: skip
            drawn.append({
                "label": label,
                "months": month_span,
                "years": self.t("cells.b.years", first=first_fy, last=last_fy),
                "aria": aria,
                "drawings": drawings,
                "base_label": self.t("cells.b.base", quarter=self.qlabel(m["row"]["period"])),
                "base_id": base["id"],
                "table": cells_row,
                "forecast_id": m["forecast_id"],
            })  # fmt: skip
        n = self.years
        heads = [self.t("cells.b.ago_first", n=n - 1)] + [
            self.t("cells.b.ago", n=k) for k in range(n - 2, 0, -1)
        ]
        return {
            "kind": "seed",
            "letter": letter,
            "title": self.t("cells.b.title"),
            "lead": self.t("cells.b.lead"),
            "minis": drawn,
            "scale": self.t("cells.b.scale", low=self.millions(low), high=self.millions(high)),
            "table_heads": heads,
            "any_derived": any(c["derived"] for d in drawn for c in d["table"]),
        }

    def _primary_annual(self, cell: dict) -> dict:
        return next(s for s in cell["history"] if s["primary"] and s["frequency"] == "year")

    def ratio_card(self, cell: dict) -> dict:
        letter = LETTERS[GROWTH]
        annual_series = self._primary_annual(cell)
        quarterly_series = next((s for s in cell["history"] if s["frequency"] == "quarter"), None)
        reference = annual_series.get("reference")
        annual = [p for p in annual_series["points"] if p["value"] is not None][-self.years :]
        quarterly = []
        if quarterly_series is not None:
            quarterly = [p for p in quarterly_series["points"]
                         if p["value"] is not None][-4 * self.years:]  # fmt: skip
        assumption = cell["rows"][0]["value"]
        same_value = all(r["value"] == assumption for r in cell["rows"])
        assumption_id = self.assumption_figure(cell, reference)

        # annual bars: the shown years, then the assumption
        values = [p["value"] for p in annual] + [assumption]
        low, high, step = _scale(values, 4, include_zero=True)
        annual_drawings = {}
        used_years = [p["fiscal_year"] for p in annual if p["used"]]
        for size, lay in ANNUAL.items():
            slots = len(annual) + 1
            slot = (lay["right"] - lay["left"]) / slots
            width = round(slot * 0.56, 1)

            def y(v, lay=lay):
                return round(lay["bottom"] - (v - low) / (high - low)
                             * (lay["bottom"] - lay["top"]), 1)  # fmt: skip

            zero = y(0.0)
            bars = []
            for i, p in enumerate(annual + [None]):
                v = assumption if p is None else p["value"]
                cx = round(lay["left"] + slot * (i + 0.5), 1)
                top, bottom = (y(v), zero) if v >= 0 else (zero, y(v))
                kind = "sup" if p is None else ("used" if p["used"] else "old")
                title = (self.t("cells.c.assumption_point", value=self.percent(v)) if p is None
                         else self.t("cells.c.year_point", year=p["fiscal_year"],
                                     value=self.percent(v)))  # fmt: skip
                if p is None:
                    xlab = (
                        self.t("cells.c.assumption")
                        if size == "l" or slot >= 60
                        else self.t("cells.c.assumption_short")
                    )
                else:
                    xlab = str(p["fiscal_year"]) if size == "l" else f"{p['fiscal_year'] % 100:02d}"
                bars.append({
                    "x": round(cx - width / 2, 1), "cx": cx, "y": top,
                    "h": max(round(bottom - top, 1), 0.5), "w": width, "kind": kind,
                    "title": title, "value": self.percent(v),
                    "vy": round(top - 6, 1) if v >= 0 else round(bottom + 14, 1),
                    "xlab": xlab,
                })  # fmt: skip
            used_bars = [b for b, p in zip(bars, annual, strict=False) if p["used"]]
            bracket = None
            if used_bars:
                x1, x2 = used_bars[0]["x"], used_bars[-1]["x"] + used_bars[-1]["w"]
                how = (reference or {}).get("how", "mean")
                bracket = {"x1": x1, "x2": x2, "cx": round((x1 + x2) / 2, 1),
                           "label": self.t(f"cells.c.bracket_{how}",
                                           value=self.percent(assumption))}  # fmt: skip
            annual_drawings[size] = {
                **lay,
                "ticks": [{"y": y(v), "label": self.tick_percent(v, step), "zero": abs(v) < 1e-12}
                          for v in _ticks(low, high, step)],
                "bars": bars,
                "show_values": slot >= VALUE_LABEL_MIN_SLOT,
                "bracket": bracket,
            }  # fmt: skip

        # quarterly bars: growth against the same quarter a year earlier, the assumption a line
        quarterly_drawings = {}
        if quarterly:
            qvalues = [p["value"] for p in quarterly] + [assumption]
            qlow, qhigh, qstep = _scale(qvalues, 4, include_zero=True)
            for size, lay in QUARTERLY.items():
                slots = len(quarterly) + 4.5
                slot = (lay["right"] - lay["left"]) / slots
                width = round(slot * 0.62, 1)

                def qy(v, lay=lay):
                    return round(lay["bottom"] - (v - qlow) / (qhigh - qlow)
                                 * (lay["bottom"] - lay["top"]), 1)  # fmt: skip

                zero = qy(0.0)
                bars = []
                for i, p in enumerate(quarterly):
                    v = p["value"]
                    cx = lay["left"] + slot * (i + 0.5)
                    top, bottom = (qy(v), zero) if v >= 0 else (zero, qy(v))
                    bars.append({"x": round(cx - width / 2, 1), "y": top,
                                 "h": max(round(bottom - top, 1), 0.5), "w": width,
                                 "title": self.t("cells.c.quarter_point",
                                                 period=self.qlabel(p["period"]),
                                                 value=self.percent(v))})  # fmt: skip
                split = round(lay["left"] + slot * (len(quarterly) + 0.5), 1)
                sup_x = round((split + lay["right"]) / 2, 1)
                # label the first quarter of each fiscal year, spaced so labels never touch
                every = 1
                while every * 4 * slot < lay["label_width"]:
                    every += 1
                firsts = [(i, p) for i, p in enumerate(quarterly) if p["fiscal_period"] == "Q1"]
                labels = []
                for k, (i, p) in enumerate(firsts[::-1]):
                    if k % every:
                        continue
                    text = (self.qlabel(p["period"]) if size == "l"
                            else self.short_label(p["period"]))  # fmt: skip
                    x = round(lay["left"] + slot * i, 1)
                    if x + lay["label_width"] > split - 4:  # would run into the assumption's label
                        continue
                    labels.append({"x": x, "label": text})
                quarterly_drawings[size] = {
                    **lay,
                    "ticks": [
                        {"y": qy(v), "label": self.tick_percent(v, qstep), "zero": abs(v) < 1e-12}
                        for v in _ticks(qlow, qhigh, qstep)
                    ],
                    "bars": bars,
                    "split": split,
                    "ref_y": qy(assumption),
                    "sup_x": sup_x,
                    "sup_label": self.t("cells.c.assumption") if size == "l"
                    else self.t("cells.c.assumption_short"),
                    "xlabels": labels[::-1],
                }  # fmt: skip

        # the note: the latest quarters beside the assumption, and when the next year enters
        recent = quarterly[-3:]
        note = note_next = None
        if len(recent) == 3:
            note = self.t(
                "cells.c.note_recent",
                values=self.listing([self.percent(p["value"]) for p in recent]),
                assumption=self.percent(assumption),
            )  # fmt: skip
        # the annual series runs to the last filed year whatever the window shows
        last_used = max((p["fiscal_year"] for p in annual_series["points"] if p["used"]),
                        default=None)  # fmt: skip
        if quarterly and last_used is not None and quarterly[-1]["fiscal_year"] > last_used:
            note_next = self.t("cells.c.note_next_year", year=quarterly[-1]["fiscal_year"],
                               company=self.company)  # fmt: skip

        annual_rows = []
        for p in annual:
            part = next(x for x in p["parts"] if x["period"] == p["period"])
            annual_rows.append({
                "label": self.period_label(p["period"]), "used": p["used"],
                "revenue": self.revenue_figure(part, letter),
                "growth": self.growth_figure(p, letter), "derived": False,
            })  # fmt: skip
        quarter_rows = []
        for p in quarterly:
            part = next(x for x in p["parts"] if x["period"] == p["period"])
            quarter_rows.append({
                "label": self.qlabel(p["period"]), "used": False,
                "revenue": self.revenue_figure(part, letter),
                "growth": self.growth_figure(p, letter), "derived": bool(part.get("derived")),
            })  # fmt: skip
        first, last = annual[0]["fiscal_year"], annual[-1]["fiscal_year"]
        return {
            "kind": "ratio",
            "letter": letter,
            "title": self.t("cells.c.title"),
            "assumption_id": assumption_id,
            "lead_key": "cells.c.lead" if same_value else "cells.c.lead_fading",
            "annual_title": self.t("cells.c.annual_title"),
            "annual_aria": self.t(
                "cells.c.annual_aria", company=self.company, first=first, last=last,
                values=", ".join(self.percent(p["value"]) for p in annual),
                assumption=self.percent(assumption),
                used=self.listing([str(y) for y in used_years]),
            ),
            "annual": annual_drawings,
            "quarterly_title": self.t("cells.c.quarterly_title"),
            "quarterly_aria": self.t(
                "cells.c.quarterly_aria",
                first=self.qlabel(quarterly[0]["period"]) if quarterly else "",
                last=self.qlabel(quarterly[-1]["period"]) if quarterly else "",
                assumption=self.percent(assumption),
            ),
            "quarterly": quarterly_drawings,
            "note": note,
            "note_next": note_next,
            "annual_rows": annual_rows,
            "quarter_rows": quarter_rows,
            "any_derived": any(r["derived"] for r in quarter_rows),
        }  # fmt: skip


def cells_view(bundle: dict, region, t, years: int, ctx: dict) -> dict:
    return CellsBuilder(bundle, region, t, years, ctx).build()
