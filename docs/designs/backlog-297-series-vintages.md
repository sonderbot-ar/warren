# Backlog #297 item 13: a series across a recast that left some of its years as first filed

Issue: https://github.com/sonderbot-ar/warren/issues/297 (item 13, and its comments of nov.10.2026) · Branch `backlog-297-series-vintages` · Status: in review.

Built here: a series note for the case v0.9.50 left open. Left in #297: items 2 (trailing sums, track records, forecast errors), 4, 5, 7, 11, 12. Found on the way and filed apart: #322 (P&G's FY2012–FY2014 revenue reads a segment's figure; needs the owner, since it changes Decision 2's "which version wins").

## Problem

Brief Q2 asks for a margin over five years. Since v0.9.50 `reported_series` says when revenue in the series carries two meanings of a tag that changed meaning (Exxon's `Revenues`, sales then total revenues and other income), because another tag kept the old figures and the engine could see the change. A company that recasts its figures without keeping the old ones under any tag gets no note, and that is the more common case:

- **Exxon:** the 10-K of 2018-02-28 cut FY2015 revenue from 259,488 to 239,854 million and FY2016 from 218,608 to 200,628 (about 8%). FY2014 and earlier were never filed again.
- **Microsoft:** the 10-K of 2018-08-03 raised FY2016 and FY2017 for the new revenue standard (ASC 606, full retrospective): 85,320 to 91,154 and 89,950 to 96,571. FY2015 and earlier keep the old standard.
- **Johnson & Johnson:** the 10-K of 2024-02-16 cut FY2021 and FY2022 by about 16% after Kenvue was separated (discontinued operations). FY2020 and earlier keep Kenvue in.
- **Coca-Cola:** the 10-K of 2020-02-24 raised FY2017 by 2.3% and FY2018 by 7.7% (31,856 to 34,300).

Each year shows its latest figure, and the reported view marks it `changed`, but a five-year chart that straddles the recast divides some years by one perimeter and others by another, with nothing to say so. The brief (Q2, "Notes on a series") says a series screen "shows each year's `changed` flag until it does". `changed` says a figure moved, not that its neighbour didn't.

## Plan

**Step 0. This doc.**

**Step 1. Find recasts** (`domains/fundamentals/facts.py`).

- `item_recasts(conn, cik, canonical_name, as_of) -> list[Recast]`. For each period of the item, walk its filings public on `as_of` in order. A filing's version is the last row of its best-ranked tag (the row `latest` mode would take from that filing alone). The filing recasts the period when its version moves by more than `RECAST_MOVE` (0.5%, the same threshold as `MEANING_CHANGE_MOVE`) from the previous filing's version, keeps its sign (a flip is #280's case), and no row of the filing, under any tag, still holds the previous value within `MEANING_CHANGE_MATCH` (0.1%). That last test is what separates a recast from a tag that changed meaning (`tag_meaning_changes`): there the old figure is still reported under another tag. Hits are grouped by filing.
- `Recast`: `canonical_name`, `accession_no`, `form`, `filed_at`, `periods` [(start, end, old, new)] by end; `largest_move(min_days)` the largest signed change as a share of the old value, among periods at least `min_days` long (None when there is none).
- `version_dates(conn, cik, canonical_name, as_of)`: (start, end) to the filing dates of every filing that reported the period under any tag, public on `as_of`.
- `side_of_recast(fact, recast, versions, filed_at) -> "before" | "after" | "mixed"`. A reported fact: "after" when any filing that reported its period is the recast's or later (refiled, recast, or first reported then); "before" when every one came earlier. A derived quarter: by its inputs' filing dates, "mixed" when they fall on both sides.
- Tests (`tests/analysis/test_series_recast.py`, Test Corp with `_recast_revenues`: from its FY2018 10-K, filed 2019-02-15, revenue for periods ending in 2017 or later is 5% lower in every filing, with no other tag keeping the old figures): the 10-K is found and dated, it moved FY2017 among the years by −5%; the 2019 10-Qs' recasts of the 2018 comparative quarters are found as their own filings; a derived quarter is before, after or mixed by its inputs.
- Exit: the full suite passes.

**Step 2. The series note** (`domains/analysis/reported.py`).

- `reported_series` adds, after any `series_mixes_meanings` notes, one `series_mixes_vintages` note per recast of revenue that splits the series: at least one period is "before" and at least one is "after" or "mixed". A series of years counts only recasts that moved a year (a 10-Q that recast quarters only is left out); a series of quarters counts every recast. When two recasts split the series the same way (J&J's 10-Q of 2023-10-27, then its 10-K of 2024-02-16, for quarters), only the first is listed.
- Params: `item` (`revenue`), `recast_on` (ISO), `form`, `accession_no`, `largest_move` (signed share, among years for a series of years), `moved_periods` (series periods the recast itself moved), `before_periods`, `after_periods`, `mixed_periods` (labels in time order; each period in exactly one of the last three), `ratios` (as for `series_mixes_meanings`).
- English fallback, Exxon FY2013–FY2017: "revenue in this series is not all on one footing: the 10-K filed 2018-02-28 changed revenue figures already reported (by up to 8.2%), including FY2015 and FY2016; FY2013 and FY2014 keep figures filed before it, never filed again; FY2015, FY2016 and FY2017 are as filed in it or later. Across that break revenue, and the ratios on it (…), may not be like for like. The filings do not say why the figures changed (a business sold, a new accounting rule, or a correction)."
- "May not", not "are not": a recast that moved FY2017 alone says nothing certain about FY2014, only that FY2014 was never put on the new footing.
- Tests: Test Corp FY2015–FY2018 gives the note with FY2015 before, FY2016–FY2018 after, FY2017 moved, −5%, the ratios and the text; FY2016–FY2019 (all after) and FY2014–FY2015 (all before) give none; the note waits for the 10-K to be public (2019-02-14 none, 2019-02-15 one); a move of half the threshold gives none; `_redefine_revenues` (a tag that changed meaning) gives only `series_mixes_meanings`; the unchanged company gives none; quarters FY2017Q1, FY2017Q4, FY2018Q1 give one note (the 10-Q's same split is not repeated), with FY2017Q4 before, because on one basis it is the 2017 year as first filed less the quarters filed with it (#264); a company with both a recast and a change of meaning gets both notes, meaning first.
- Exit: the full suite passes; `reported_period` is untouched; `ruff check` and `ruff format --check` clean.

**Step 3. Real data** (snapshot of nov.10.2026, as of 2026-11-09). Every run of five consecutive fiscal years starting FY2009–FY2021 and of eight consecutive quarters starting FY2009Q1–FY2025Q4, eight companies; list each note. Expected: Exxon, Microsoft, J&J and Coca-Cola year runs that straddle the recasts above; P&G (its 2012, 2015 and 2016 10-Ks) plus the artefacts of #322; nothing on the recent five years. Results below.

## Step 3 results (snapshot of nov.10.2026, as of 2026-11-09)

Year runs (five years starting FY2009 to FY2021, 13 per company):

| Company | Runs with a note | Recast filing (largest move in a year) | Before → after |
|---|---|---|---|
| AAPL, CAT, WMT | 0 | (Apple's 10-K/A of 2010-01-25 recast FY2007–FY2009; no run starting FY2009 holds an earlier year) | |
| XOM | 4 (starting FY2011–FY2014) | 10-K 2018-02-28 (−8.2%) | ≤FY2014 → FY2015 on |
| MSFT | 4 (FY2012–FY2015) | 10-K 2018-08-03 (+7.4%) | ≤FY2015 → FY2016 on |
| KO | 4 (FY2013–FY2016) | 10-K 2020-02-24 (+7.7%) | ≤FY2016 → FY2017 on |
| JNJ | 4 (FY2017–FY2020) | 10-K 2024-02-16 (−16.0%) | ≤FY2020 → FY2021 on |
| PG | 5 (FY2009–FY2013) | 10-K 2012-08-08 (−1.8%); 10-K 2016-08-09 (−7.6%); and 10-Ks 2014-08-08 (−66.1%) and 2015-08-07 (+174.4%) | see below |

- **P&G.** Two real recasts (the 10-K of 2012-08-08 moved FY2010 and FY2011 by about −1.8%; that of 2016-08-09 moved FY2014 and FY2015 by about −7.6%, the beauty brands sold to Coty). The −66% and +174% "recasts" are #322: the 10-K of 2014-08-08 tagged one segment's sales as `Revenues` for FY2012–FY2014, and the 10-K of 2015-08-07 tagged the total again. The note is right that those years are not on one footing with their neighbours; it can't say the cause is a tagging error. Once #322 is decided they become ordinary recasts or disappear. A P&G run starting FY2009 to FY2011 carries two or three notes, one per recast.
- **Recent five years.** No company's FY2021–FY2025 run carries a note.
- Walmart's 2011 and 2012 10-Ks recast quarters only (−0.7%), so years get none; quarters below.

Quarter runs: (filled in when the eight-quarter scan finishes; see "Where the work stopped" if it is empty.)

## Alternatives considered

- **Leave it to each year's `changed` flag.** A flag says a figure moved; the student needs to know that its neighbour did not. Comparing flags also needs filing dates the app does not have.
- **Compare each period's latest filing date with the others'.** A 10-K repeats three years without changing them, so different filing dates are normal; only a filing that moved figures marks a break.
- **Restate the old years onto the new footing.** Impossible from the filings: nothing gives Exxon's FY2014 on the 2018 basis.
- **Fold it into `series_mixes_meanings`.** Different cause, different evidence (another tag keeps the old figure there; here nothing does), different wording ("not comparable" against "may not be"). Two codes keep the app's ranking simple.
- **Flag every recast, however small.** 0.5% is the threshold the meaning-change scan already uses; `largest_move` lets the app grade it (Walmart's −0.7% quarter recasts are real reclassifications, but minor).

## Files

`domains/fundamentals/facts.py`, `domains/analysis/reported.py`, `tests/analysis/test_series_recast.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q2 (a margin over five years) and Q1 when a few quarters are shown together; closes the gap the brief names under "Notes on a series" ("the engine does not flag that yet (#297 item 13)").

- **Added:** note code `series_mixes_vintages` on `reported_series(...).notes`, params as in Step 2. Listed after any `series_mixes_meanings`.
- **Nothing renamed or removed; no value changes.** `reported_period` is untouched.
- For the app: show it above the chart or table like `series_mixes_meanings`, but in the brief's middle group ("why it comes from where it does"), after a meaning note: the break may be real or small, and `largest_move` says how big the recast was. Mark the break between `before_periods` and the rest with a mark or pattern, not colour alone. Suggested Spanish: "En esta serie no todos los ingresos están sobre la misma base: el {form} presentado el {fecha} cambió cifras de ingresos ya publicadas (hasta {movimiento}){, entre ellas {moved}}; {before} conservan las cifras presentadas antes y no se volvieron a presentar. Los ingresos y los márgenes calculados sobre ellos pueden no ser comparables de un lado al otro. Las presentaciones no dicen por qué cambiaron (venta de un negocio, una norma contable nueva o una corrección)." Never "reexpresado" (IAS 8 error correction) or "ajustado por inflación".

## Limits

- Only revenue, as the other series note.
- The engine does not know why figures moved; the text says so.
- A recast is dated by the filing that first moved figures; a later filing that moves them again is its own recast and note.
- P&G's #322 tagging error shows as two large recasts until #322 is decided.
- Growth on a single period across a recast (Apple FY2009Q4 against FY2008Q4, #297 comment of nov.10.2026) is not noted here: this is the series note only.
