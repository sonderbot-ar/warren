# Backlog #297 item 2 (series part): a run of periods that crosses a tag's change of meaning

Issue: https://github.com/sonderbot-ar/warren/issues/297 · Branch `backlog-297-series-meaning` · Status: design (nov.10.2026).

Built here: item 2 for the case the front-end is waiting on, a series of periods asked together (brief Q2, "how has the operating margin changed over five years"). Left in #297: item 2 for trailing sums, track records and forecast errors; items 1 (run note), 4, 5, 7, 11, 12, 13.

## Problem

Brief Q2 asks for a ratio over five fiscal years. The app calls `reported_period` once per year and lays the answers side by side. Since v0.9.49 each year's revenue line says when its *own* figures carry different meanings of a tag that changed meaning, but a year whose figures all carry one meaning gets no note, and nothing compares the years with each other.

Exxon is the case. Its `us-gaap:Revenues` meant sales until the 10-Q of 2019-11-06 and total revenues and other income from then on (`facts.MeaningChange`). The 10-K of 2020-02-26 refiled 2017 and 2018 under the new meaning, so as of today:

- FY2015 and FY2016: last filed in the 10-K of 2018-02-28, before the change: sales (old meaning).
- FY2017 to FY2026: total revenues and other income (new meaning).

A five-year series FY2015–FY2019 therefore divides by sales for two years and by a broader total for three. Operating margin, gross margin, capex and D&A shares and net margin all move at the break for a reason that is not the business. The brief (Q2, "Notes on a reported figure") says the series screen for Exxon "waits for it or says it". The app could compare each year's meaning itself, but only when a year has a note; a year whose figures agree has none, so the app cannot tell old from new there. The engine knows; it should say so.

## Plan

**Step 0. This doc.**

**Step 1. `reported_series` and its note.**

- New call `domains.analysis.reported.reported_series(conn, ticker, periods, as_of) -> ReportedSeries`. `periods`: a list of period texts or `Period`s (the forms `reported_period` takes, `latest-year` and `latest-quarter` included), 1 to 20 of them, all fiscal years or all quarters (a mix is refused with `ReportedError`, since a year and a quarter are not a series). Duplicates are refused. The answer lists the periods in time order, whatever order they were asked in.
- `ReportedSeries`: `ticker`, `cik`, `company_name`, `as_of`, `periods` (one `ReportedPeriod` each, exactly as `reported_period` returns it; nothing about a single period changes), `notes` (list of `Coded`). `to_dict()` gives plain JSON as `ReportedPeriod.to_dict` does.
- Each period's revenue meaning is `facts.meaning_state` on the very fact its revenue line shows (the latest version known on `as_of`, on one basis for a quarter), with the filings' dates, so a derived quarter worked out across the change is "mixed". Only revenue, as in v0.9.46 and v0.9.49 (the only item scanned for a change of meaning).
- Note `series_mixes_meanings` when the periods' revenue meanings for one change are not all the same, or any is "mixed". Params: `item` (`revenue`), `tag`, `other_tag`, `changed_on` (ISO), `form`, `accession_no` (the first filing that shows the change, as on the other `tag_changed_meaning` notes), `old_periods`, `new_periods`, `mixed_periods` (period labels in time order; each period is in exactly one list), `ratios` (sorted names of the ratios whose `uses` include a revenue line in any period of the series: today `capex_share`, `da_share`, `gross_margin`, `net_margin`, `operating_margin`, `revenue_growth_yoy` where present). English fallback, for Exxon FY2015–FY2019: "revenue in this series is us-gaap:Revenues with two meanings: FY2015 and FY2016 carry the tag's earlier meaning, FY2017, FY2018 and FY2019 the meaning the 10-Q filed 2019-11-06 gave it. Across that break revenue, and the ratios on it (…), are not like for like; the earlier meaning's figures are still filed under us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax."
- A series wholly on one meaning, old or new, gets no note. A company with no change gets none. A period whose fact's tag never changed (another tag that period) counts as old when its tag is not the changed one: it cannot carry the new meaning. (Exxon's revenue is `Revenues` in every year since 2009; this rule only matters for a company that switched tags.)
- Tests (`tests/analysis/test_reported_series.py`, Test Corp with `Revenues` 4% higher from its Q3 2019 10-Q, the old figures kept under the contract-revenue tag, the `_redefine_revenues` edit of v0.9.46): FY2016–FY2019 gives the note with FY2016 old and FY2017–FY2019 new, the six ratio names, the text naming both tags and the date; FY2017–FY2019 (all new) and FY2016 alone give none; periods asked out of order come back in time order; a quarter series FY2018Q1–FY2019Q2 names its old and new quarters; a derived quarter worked out across the change is listed in `mixed_periods`; the note waits until the change is public (as of 2019-12-31 vs later, as the line note's test does); unchanged Test Corp gives no note; a mixed year-and-quarter list, a duplicate, an empty list and 21 periods are refused; each `ReportedPeriod` in the series equals `reported_period`'s answer for that period; `to_dict` is plain JSON.
- Exit: the full suite passes; nothing in `reported_period` changes.

**Step 2. The command.**

- `python -m domains.analysis series --ticker XOM --period FY2015 --period FY2016 ... [--as-of D] [--json]`. Text: one row per period with revenue (and its tag), operating margin, gross margin and net margin, then the series notes. JSON: `ReportedSeries.to_dict()`. Without `--as-of`, the last day ended in New York, with the same notes on standard error as `reported`.
- Tests: the text names the break and the periods; `--json` is the call's `to_dict`; a refused list exits 1 with `FAILED:`.
- Exit: the full suite passes; `ruff check` and `ruff format --check` clean.

**Step 3. Real data** (latest snapshot, as of 2026-11-09). Every run of five consecutive fiscal years FY2009–FY2026 for the eight companies, and of eight consecutive quarters: list each note. Expected: notes only for Exxon, on year runs that include FY2016 or earlier together with FY2017 or later, and on quarter runs that cross the change; nothing for the other seven. Results written here.

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
- For the app: Q2 can call `reported_series` once per company instead of `reported_period` five times, and must show `series_mixes_meanings` on the chart or table, first among the series' notes (it says the series cannot be read as asked across the break, the brief's first group). Mark the break between the last period of `old_periods` and the first of `new_periods`; shade `mixed_periods`. Suggested Spanish: "En esta serie, los ingresos de {empresa} miden dos líneas distintas: {old} corresponden a las ventas y {new} a los ingresos totales y otros ingresos según la presentación desde el {fecha}. Entre esos años, los ingresos y los márgenes sobre ellos no son comparables." Name the lines only for Exxon until item 5 gives labels; otherwise "una definición anterior" and "la definición nueva". Never "reexpresado".

## Limits

- Only revenue, and only a change the filings show (`tag_meaning_changes`); a reclassification with no other tag (item 13) is not seen.
- Trailing sums, track records and forecast errors across the change are not flagged (item 2's other half).
- A derived quarter is judged mixed by its inputs' filing dates, not their tags (as in v0.9.49).
