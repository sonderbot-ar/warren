# Backlog #297 item 2 (series part): a run of periods that crosses a tag's change of meaning

Issue: https://github.com/sonderbot-ar/warren/issues/297 · Branch `backlog-297-series-meaning` · Status: built (nov.10.2026); PR to come.

Built here: item 2 for the case the front-end is waiting on, a series of periods asked together (brief Q2, "how has the operating margin changed over five years"). Left in #297: item 2 for trailing sums, track records and forecast errors; items 1 (run note), 4, 5, 7, 11, 12, 13.

## Problem

Brief Q2 asks for a ratio over five fiscal years. The app calls `reported_period` once per year and lays the answers side by side. Since v0.9.49 each year's revenue line says when its *own* figures carry different meanings of a tag that changed meaning, but a year whose figures all carry one meaning gets no note, and nothing compares the years with each other.

Exxon is the case. Its `us-gaap:Revenues` meant sales until the 10-Q of 2019-11-06 and total revenues and other income from then on (`facts.MeaningChange`). The 10-K of 2020-02-26 refiled 2017 and 2018 under the new meaning, so as of today:

- FY2010 to FY2016: last filed in a 10-K before the change (FY2016 in the 10-K of 2019-02-27, FY2015 in that of 2018-02-28): the tag's earlier meaning.
- FY2017 to FY2025: total revenues and other income (new meaning). (FY2026 is not reported by 2026-11-09, and Exxon's filings on this CIK stop on 2026-08-03.)

The earlier side is not one consistent line either: the 10-K of 2018-02-28 cut FY2015 and FY2016 revenue by about 8% (259,488 to 239,854; 218,608 to 200,628) and no other tag kept the old figures, so FY2014 and earlier sit on a third basis that the filings' tags do not reveal (analyst; #297 item 13). This step does not detect that; the note says so.

A five-year series FY2015–FY2019 therefore divides by sales for two years and by a broader total for three. Operating margin, gross margin, capex and D&A shares and net margin all move at the break for a reason that is not the business. The brief (Q2, "Notes on a reported figure") says the series screen for Exxon "waits for it or says it". The app could compare each year's meaning itself, but only when a year has a note; a year whose figures agree has none, so the app cannot tell old from new there. The engine knows; it should say so.

## Plan

**Step 0. This doc.**

**Step 1. `reported_series` and its note.**

- New call `domains.analysis.reported.reported_series(conn, ticker, periods, as_of) -> ReportedSeries`. `periods`: a list of period texts or `Period`s (the forms `reported_period` takes, `latest-year` and `latest-quarter` included), 1 to 20 of them, all fiscal years or all quarters (a mix is refused with `ReportedError`, since a year and a quarter are not a series). Duplicates are refused. The answer lists the periods in time order, whatever order they were asked in.
- `ReportedSeries`: `ticker`, `cik`, `company_name`, `as_of`, `periods` (one `ReportedPeriod` each, exactly as `reported_period` returns it; nothing about a single period changes), `notes` (list of `Coded`). `to_dict()` gives plain JSON as `ReportedPeriod.to_dict` does.
- Each period's revenue meaning is `facts.meaning_state` on the very fact its revenue line shows (the latest version known on `as_of`, on one basis for a quarter), with the filings' dates, so a derived quarter worked out across the change is "mixed". Only revenue, as in v0.9.46 and v0.9.49 (the only item scanned for a change of meaning).
- A period's state for a change: its `meaning_state` when the fact's tag is the changed one; "old" when the fact is under the changed tag before the change or under `other_tag` (which keeps the earlier meaning by construction); "other" when the fact is under another tag (nothing is known of its meaning, so it is not called the earlier one; analyst).
- Note `series_mixes_meanings`, one per change (`tag_meaning_changes` can list several; ordered by filing date), when any period is "mixed", or at least one is "new" and at least one is not. A series of old and other periods only gets none: no period carries the new meaning, and what lies between them is not known. Params: `item` (`revenue`), `tag`, `other_tag`, `changed_on` (ISO), `form`, `accession_no` (the first filing that shows the change, as on the other `tag_changed_meaning` notes), `old_periods`, `new_periods`, `mixed_periods`, `other_tag_periods` (period labels in time order; each period is in exactly one list), `ratios` (sorted names of the ratios whose `uses` include a revenue line in any period of the series, so a coded gap with no `uses` is left out: `capex_share`, `da_share`, `gross_margin`, `net_margin`, `operating_margin`, `revenue_growth_yoy` when computed; `net_debt` uses revenue only for its date and unit, not as a divisor, and is left out). English fallback, for Exxon FY2015–FY2019: "revenue in this series is us-gaap:Revenues with more than one meaning: FY2015 and FY2016 carry the tag's earlier meaning; FY2017, FY2018 and FY2019 the meaning the 10-Q filed 2019-11-06 gave it. Across that break revenue, and the ratios on it (…), are not like for like. Only the periods the change shows are also filed on the earlier meaning, under us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax. This says nothing about other changes within either side." (The last two sentences answer the professor: the other tag does not let a student rebuild every year; and the analyst: a side is not claimed to be like for like.)
- A period that cannot be answered (revenue not reported by `as_of`, or an unknown period) refuses the whole series with `reported_period`'s `ReportedError`, as asking that one period would. Time order is by `period_end`. `latest-year` and `latest-quarter` are resolved first, so a duplicate is caught after resolving (`FY2019` and `latest-year` collide when FY2019 is the latest).
- The first period's `revenue_growth_yoy` uses the year before the series. In a series wholly on the new meaning whose first year's prior is old (Exxon FY2017–FY2019) the series gets no note, but that growth figure still carries v0.9.46's growth note `tag_changed_meaning` (analyst).
- A series wholly on one meaning, old or new, gets no note. A company with no change gets none.
- Tests (`tests/analysis/test_reported_series.py`, Test Corp with `Revenues` 4% higher from its Q3 2019 10-Q, the old figures kept under the contract-revenue tag, the `_redefine_revenues` edit of v0.9.46): FY2016–FY2019 gives the note with FY2016 old and FY2017–FY2019 new, the six ratio names, the text naming both tags and the date; FY2017–FY2019 (all new) and FY2016 alone give none; periods asked out of order come back in time order; a quarter series FY2018Q1–FY2019Q2 names its old and new quarters; FY2018Q4 (the new 2018 year less old and new quarters) is listed in `mixed_periods`, alone too; a FY2015 filed under `SalesRevenueNet` is in `other_tag_periods`, and old plus other with no new period gives no note; the note waits until the change is public (as of 2019-12-31 vs later, as the line note's test does); unchanged Test Corp gives no note; a mixed year-and-quarter list, a duplicate, an empty list and 21 periods are refused; each `ReportedPeriod` in the series equals `reported_period`'s answer for that period; `to_dict` is plain JSON.
- Exit: the full suite passes; nothing in `reported_period` changes.

**Step 2. The command.**

- `python -m domains.analysis series --ticker XOM --period FY2015 --period FY2016 ... [--as-of D] [--json]`. Text: one row per period with revenue (and its tag), operating margin, gross margin and net margin, then the series notes. JSON: `ReportedSeries.to_dict()`. Without `--as-of`, the last day ended in New York, with the same notes on standard error as `reported`.
- Tests: the text names the break and the periods; `--json` is the call's `to_dict`; a refused list exits 1 with `FAILED:`.
- Exit: the full suite passes; `ruff check` and `ruff format --check` clean.

**Step 3. Real data** (latest snapshot, as of 2026-11-09). Every run of five consecutive fiscal years starting FY2009–FY2021 for the eight companies, and of eight consecutive quarters: list each note. Expected: notes only for Exxon, on year runs that include FY2016 or earlier together with FY2017 or later, and on quarter runs that cross the change; nothing for the other seven. Results written here.

## Step 3 results (snapshot of nov.05.2026, as of 2026-11-09)

Every run of five consecutive fiscal years starting FY2009–FY2021 (13 per company) and of eight consecutive quarters starting FY2009Q1–FY2025Q4 (68 per company), eight companies.

| Company | Year runs with a note | Year runs refused | Quarter runs with a note | Quarter runs refused |
|---|---|---|---|---|
| AAPL, MSFT, KO, PG, JNJ, CAT | 0 | 0 | 0 | 2–5 each (runs reaching quarters not yet reported) |
| WMT | 0 | 5 | 0 | 12 |
| XOM | 4 | 0 | 6 | 38 |

- **Exxon, years.** Notes on exactly the four runs that hold FY2016 or earlier together with FY2017 or later (starting FY2013 to FY2016), e.g. FY2015–FY2019: old FY2015, FY2016; new FY2017–FY2019; nothing mixed or other. Ratios: `capex_share`, `da_share`, `net_margin`, `operating_margin`, `revenue_growth_yoy` (Exxon tags no cost of revenue, so no gross margin). FY2017–FY2021 gets none, as designed; its first year's growth carries v0.9.46's note.
- **Exxon, quarters.** Six runs, those starting FY2017Q1 to FY2018Q2: old up to FY2018Q2, new from FY2018Q3 (the quarters the 10-Q of 2019-11-06 and later filings refiled). No quarter is mixed: on one basis, FY2017Q4 and FY2018Q4 are worked out on a single meaning (v0.9.49's table). Runs starting FY2018Q3 or later are all new; before FY2017 all old.
- **Refusals.** A run refuses when any of its periods is not reported by the as-of date, as `reported_period` does: Exxon's quarters before FY2011 (its first 10-Qs in the data are 2011) and after FY2026Q1 (filings on this CIK stop 2026-08-03); the other companies' runs reaching quarters after their last 10-Q. **Walmart** refuses every five-year run holding FY2014: the year ending January 2014 is labelled FY2013, beside the year ending January 2013, and there is no FY2014 (the year ending January 2015 is FY2015). That label gap is older than this item and also hits `reported_period`; filed as a backlog issue. A screen asking Walmart's last five years (FY2022–FY2026) is not affected.
- Nothing for the other seven, as expected. The known untagged breaks (Exxon FY2014/FY2015, MSFT, JNJ, KO; Limits) get no note.

## Design review (nov.10.2026)

- **Analyst (NO-GO, one blocker).** The old side would read as one consistent line, but Exxon's FY2014 and FY2015 differ by an untagged 8% cut in the 10-K of 2018-02-28. Fixed by wording, not detection: the text and the Spanish no longer say the old side is "sales" or like for like ("This says nothing about other changes within either side"), and the cut is named above and in Limits. Detecting it is #297 item 13, a separate scan; the analyst's evidence (and MSFT's ASC 606 restatement of FY2016–FY2017, JNJ's Kenvue recast of FY2022–FY2023, KO FY2018) is added to #297. Ideas taken: other-tag periods kept apart (`other_tag_periods`); the first year's growth stated; `net_debt` left out on purpose; FY2016's filing date corrected.
- **Professor (GO).** Defensible (FASB Concepts Statement 8 QC20–QC22, IASB Conceptual Framework 2.24–2.26: comparability is a property of a comparison, so a series note). Taken: the Spanish no longer says "presentación" (the statement's lines did not change, only the tag), keeps "etiqueta XBRL", says "de un lado al otro del cambio" (works for quarters), and has a sentence for mixed quarters; the English no longer suggests the other tag rebuilds every year. Glossing "consistencia" is for the app (front-end).
- **Explainer.** B1 (an unreported period): refused, stated above; Step 3 runs end at FY2025. B2 (which quarter is mixed): named (FY2018Q4). B3 (several changes): one note per change, stated. I1, I2, I3 answered above.
- **Product lead.** Blocker: "name the lines only for Exxon" would need company logic in the app; dropped, the Spanish is generic until item 5 gives labels. The rest taken in Product impact.

## Alternatives considered

- **Let the app compare the years' `meaning_note` params.** A year whose figures agree carries no note, so the app cannot tell an old year from a year that never changed. It would also have to know the rule, and design principle "the engine says, the app shows" puts that in the engine.
- **Add `meaning` to every line, always.** Lets the app compare, but adds a field to every line of every answer for one company's case, and still leaves the comparison to the app.
- **Put the note on each period's ratios ("this year divides by the new meaning").** Every Exxon margin from 2017 on would carry a note forever, though a margin on one meaning is fine on its own; the problem is only the comparison, which needs a series.
- **Restate the old years onto the new meaning, or the new onto the old.** Item 4 (like-for-like growth) and item 11 (margins on sales) ask a version of this. It produces new numbers, needs care about which line the other tag holds, and is a separate item; this step only says where the break is.

## Files

`domains/analysis/reported.py`, `domains/analysis/__main__.py`, `tests/analysis/test_reported_series.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (nothing: backlog items have no row).

## Product impact

Serves brief Q2 (a ratio over five years, two companies side by side) and Q1 when the app shows a few quarters together.

- **Added:** the call `reported_series(conn, ticker, periods, as_of)` and the command `series`. `to_dict`: `ticker`, `cik`, `company_name`, `as_of`, `periods` (each exactly a `reported_period(...).to_dict()`), `notes` (list of `{code, params, text}`).
- **Added:** note code `series_mixes_meanings`, params as in Step 1.
- **Nothing renamed or removed; no value changes.** `reported_period` is untouched, so screens built on it keep working.
- For the app: Q2 can call `reported_series` once per company instead of `reported_period` five times, and must show `series_mixes_meanings` above the chart or table, ahead of any single figure's notes (it says the series cannot be read as asked across the break, the brief's first group; the brief's order list is for one figure, so the front-end adds a sentence for series notes). Mark the break between the periods of different meanings with a mark or pattern, not colour alone (principles, accessibility); mark `mixed_periods` and `other_tag_periods` the same way. The margins' *Fuente* tab of an affected period can repeat a one-line mention built from the note. Dates in the principles' format (6 nov 2019), never ISO.
- Suggested Spanish (product lead and professor): "En esta serie, la etiqueta XBRL de ingresos de {empresa} no mide lo mismo en todos los periodos: {old} usan la definición anterior y {new} la definición nueva, desde que el {form} presentado el {fecha} cambió lo que mide la etiqueta. Los ingresos y los márgenes calculados sobre ellos no son comparables de un lado al otro del cambio." For `mixed_periods`: "{mixed} mezcla las dos definiciones." For `other_tag_periods`: "{other} usa otra etiqueta, de definición desconocida." Do not name the lines ("ventas", "total de ingresos y otros ingresos") until item 5 gives labels from the filings, and never say "reexpresado" or "presentación".

## Limits

- Only revenue, and only a change the filings show (`tag_meaning_changes`); a reclassification with no other tag (item 13) is not seen: Exxon FY2014 against FY2015 (an 8% cut in the 10-K of 2018-02-28), MSFT FY2016–FY2017 restated for ASC 606 against FY2015, JNJ FY2022–FY2023 recast after Kenvue, KO FY2018 (analyst). A series across those gets no note.
- Trailing sums, track records and forecast errors across the change are not flagged (item 2's other half).
- A derived quarter is judged mixed by its inputs' filing dates, not their tags (as in v0.9.49).
