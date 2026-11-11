# Backlog #297 item 13: a series across a recast that left some of its years as first filed

Issue: https://github.com/sonderbot-ar/warren/issues/297 (item 13, and its comments of nov.10.2026) · Branch `backlog-297-series-vintages` · Status: in review (design review done, nov.11.2026).

Built here: a series note for the case v0.9.50 left open. Left in #297: items 2 (trailing sums, track records, forecast errors), 4, 5, 7, 11, 12. Found on the way and filed apart: #322 (P&G's FY2012–FY2014 revenue reads a segment's figure; needs the owner, since it changes Decision 2's "which version wins").

## Problem

Brief Q2 asks for a margin over five years. Since v0.9.50 `reported_series` says when revenue in the series carries two meanings of a tag that changed meaning (Exxon's `Revenues`, sales then total revenues and other income), because another tag kept the old figures and the engine could see the change. A company that recasts its figures without keeping the old ones under any tag gets no note, and that is the more common case:

- **Exxon:** the 10-K of 2018-02-28 cut FY2015 revenue from 259,488 to 239,854 million and FY2016 from 218,608 to 200,628 (about 8%). FY2014 and earlier have no later version in the filings' tagged data (the 10-K's five-year summary may restate them, as the professor notes for 2013 and 2014; that table is not tagged).
- **Microsoft:** the 10-K of 2018-08-03 raised FY2016 and FY2017 for the new revenue standard (ASC 606, full retrospective): 85,320 to 91,154 and 89,950 to 96,571. FY2015 and earlier keep the old standard (the SEC let filers leave the fourth and fifth years of the five-year table on the old basis, with a note that they are not comparable: S-K Item 301, Instruction 2; CorpFin FRM 11100.1).
- **Johnson & Johnson:** the 10-K of 2024-02-16 cut FY2021 and FY2022 by about 16% after Kenvue was separated (discontinued operations). FY2020 and earlier keep Kenvue in.
- **Coca-Cola:** the 10-K of 2020-02-24 raised FY2017 by 2.3% and FY2018 by 7.7% (31,856 to 34,300).

Each year shows its latest figure, and the reported view marks it `changed`, but a five-year chart that straddles the recast divides some years by one perimeter and others by another, with nothing to say so. The brief (Q2, "Notes on a series") says a series screen "shows each year's `changed` flag until it does". `changed` says a figure moved, not that its neighbour didn't.

## Plan

**Step 0. This doc.**

**Step 1. Find recasts** (`domains/fundamentals/facts.py`).

- `item_recasts(conn, cik, canonical_name, as_of) -> list[Recast]`. For each period of the item, walk its filings public on `as_of` in order. A filing's version is the last row of that filing's best-ranked tag. A recast counts for a period only when that tag is the one `latest` mode shows for the period (the best-ranked tag across all filings), so a filing that reports the period only under a lower-ranked tag never changes the figure on screen (design review, analyst blocker 1). The filing recasts the period when its version moves by more than `RECAST_MOVE` (0.5%, the same threshold as `MEANING_CHANGE_MOVE`) from the previous filing's version, keeps its sign (a flip is #280's case), and no row of the filing, under any tag, still holds the previous value within `MEANING_CHANGE_MATCH` (0.1%). That last test is what separates a recast from a tag that changed meaning (`tag_meaning_changes`): there the old figure is still reported under another tag. Hits are grouped by filing.
- `Recast`: `canonical_name`, `accession_no`, `form`, `filed_at`, `periods` [(start, end, old, new)] by end; `largest_move(min_days)` the largest signed change as a share of the old value, among periods at least `min_days` long (None when there is none).
- `version_dates(conn, cik, canonical_name, as_of)`: (start, end, tag) to the filing dates of every filing that reported the period under that tag, public on `as_of`.
- `side_of_recast(fact, recast, versions, filed_at) -> "before" | "after" | "mixed"`. A reported fact: "after" when any filing that reported its period under the fact's own tag is the recast's or later (refiled, recast, or first reported then); "before" when every one came earlier. A derived quarter: by its inputs' filing dates, "mixed" when they fall on both sides.
- Tests (`tests/analysis/test_series_recast.py`, Test Corp with `_recast_revenues`: from its FY2018 10-K, filed 2019-02-15, revenue for periods ending in 2017 or later is 5% lower in every filing, with no other tag keeping the old figures): the 10-K is found and dated, it moved FY2017 among the years by −5%; the 2019 10-Qs' recasts of the 2018 comparative quarters are found as their own filings; a derived quarter is before, after or mixed by its inputs.
- Exit: the full suite passes.

**Step 2. The series note** (`domains/analysis/reported.py`).

- `reported_series` adds, after any `series_mixes_meanings` notes, one `series_mixes_vintages` note per recast of revenue that splits the series: at least one period is "before" and at least one is "after" or "mixed". A series of years counts only recasts that moved a year (a 10-Q that recast quarters only is left out); a series of quarters counts every recast. When two recasts split the series the same way (J&J's 10-Q of 2023-10-27, then its 10-K of 2024-02-16, for quarters), only the first is listed.
- Params: `item` (`revenue`), `recast_on` (ISO), `form`, `accession_no`, `largest_move` (signed share, among years for a series of years), `moved_periods` (series periods the recast itself moved), `before_periods`, `after_periods`, `mixed_periods` (labels in time order; each period in exactly one of the last three), `ratios` (as for `series_mixes_meanings`).
- Notes are listed in order of `recast_on` (then accession), after any `series_mixes_meanings`.
- English fallback, Exxon FY2013–FY2017: "revenue in this series is not all on one footing: the 10-K filed 2018-02-28 lowered revenue figures already reported (by up to 8.2%), including FY2015 and FY2016; FY2013 and FY2014 keep figures filed before it, with no later version in the filings' tagged data; FY2015, FY2016 and FY2017 are as filed in it or later. Across that break revenue, and the ratios on it (capex_share, da_share, net_margin, operating_margin, revenue_growth_yoy), may not be like for like. Warren does not know why the figures changed (for example a business separated, sold or brought back, a new accounting rule, a change in presentation, or a correction); the 10-K explains it." "Lowered" or "raised" follows the sign of `largest_move`; the "including" clause is dropped when the recast moved no period of the series; an "is (are) worked out from figures on both sides" clause names `mixed_periods`.
- "May not", not "are not": a recast that moved FY2017 alone says nothing certain about FY2014, only that FY2014 was never put on the new footing.
- Tests: Test Corp FY2015–FY2018 gives the note with FY2015 before, FY2016–FY2018 after, FY2017 moved, −5%, the ratios and the text; FY2016–FY2019 (all after) and FY2014–FY2015 (all before) give none; the note waits for the 10-K to be public (2019-02-14 none, 2019-02-15 one); a move of half the threshold gives none; `_redefine_revenues` (a tag that changed meaning) gives only `series_mixes_meanings`; the unchanged company gives none; quarters FY2017Q1, FY2017Q4, FY2018Q1 give one note (the 10-Q's same split is not repeated), with FY2017Q4 before, because on one basis it is the 2017 year as first filed less the quarters filed with it (#264); a company with both a recast and a change of meaning gets both notes, meaning first.
- Exit: the full suite passes; `reported_period` is untouched; `ruff check` and `ruff format --check` clean.

**Step 3. Real data** (snapshot of nov.10.2026, as of 2026-11-09). Every run of five consecutive fiscal years starting FY2009–FY2021 and of eight consecutive quarters starting FY2009Q1–FY2025Q4, eight companies; list each note. Expected: Exxon, Microsoft, J&J and Coca-Cola year runs that straddle the recasts above; P&G (its 2012, 2015 and 2016 10-Ks) plus the artefacts of #322; nothing on the recent five years. Results below.

## Step 3 results (snapshot of nov.10.2026, as of 2026-11-09; after the design review's fix)

Every run of five consecutive fiscal years starting FY2009 to FY2021 (13 per company), and of eight consecutive quarters starting in Q1 of each year 2009 to 2024 (16 per company; the full 68-start quarter scan took too long for this run), eight companies. Script: one `reported_series` call per run, notes with code `series_mixes_vintages` listed.

| Company | Year runs noted | Recast (largest move in a year) | Break | Quarter runs noted |
|---|---|---|---|---|
| AAPL, CAT, WMT | 0 | (Apple's 10-K/A of 2010-01-25 recast FY2007–FY2009; no run here holds a year before it) | | 0 (WMT: 1 refused) |
| XOM | 4 (starting FY2011–FY2014) | 10-K 2018-02-28 (−8.2%) | FY2014 \| FY2015 | 0 (8 refused, as in v0.9.50) |
| MSFT | 4 (FY2012–FY2015) | 10-K 2018-08-03 (+7.4%, ASC 606) | FY2015 \| FY2016 | 2 (the 10-Qs of 2017-10-26 and 2018-01-31 recast the FY2016–FY2017 quarters) |
| KO | 4 (FY2013–FY2016) | 10-K 2020-02-24 (+7.7%) | FY2016 \| FY2017 | 2 (the 10-Qs of 2019-07-25 and 2019-10-24, then the 10-K: up to three notes per run; FY2018Q4 mixed) |
| JNJ | 4 (FY2017–FY2020) | 10-K 2024-02-16 (−16.0%, Kenvue) | FY2020 \| FY2021 | 3 (the 10-Qs of 2023-10-27 and 2024-07-25) |
| PG | 6 (FY2009–FY2014) | 10-K 2012-08-08 (−1.8%); 10-K 2014-08-08 (−66.1%, #322); 10-K 2016-08-09 (−7.2%) | | 5 |

- **Walmart** no longer gets a note (design review, analyst blocker 2): its 10-Ks tag quarters only as net sales, its 10-Qs as total revenues, and the figure shown is total revenues, so the 10-Ks changed nothing a reader sees.
- **P&G.** Notes now follow the figures shown. The 10-K of 2014-08-08 is listed with −66% because the figures shown for FY2012 and FY2013 are its segment figures (#322, waiting on the owner); the note is true to what is on screen, and #322 fixes the screen. The 10-K of 2015-08-07 is no longer listed (it gave the right totals under a lower-ranked tag, which is not what is shown). The 10-K of 2016-08-09 lists only FY2015 as moved.
- **Recent five years.** No company's FY2021–FY2025 run, nor any run of eight quarters from 2024, carries a note.
- **Quarters.** A company that recasts quarter by quarter in its 10-Qs (Coca-Cola in 2019, J&J in 2023–2024) gives one note per 10-Q whose split differs. Accurate, but a screen may want to show only the latest (product lead: the app shows them in order).

## Alternatives considered

- **Leave it to each year's `changed` flag.** A flag says a figure moved; the student needs to know that its neighbour did not. Comparing flags also needs filing dates the app does not have.
- **Compare each period's latest filing date with the others'.** A 10-K repeats three years without changing them, so different filing dates are normal; only a filing that moved figures marks a break.
- **Restate the old years onto the new footing.** Not from the tagged data: no tagged figure gives Exxon's FY2014 on the 2018 basis (an untagged five-year summary might).
- **Fold it into `series_mixes_meanings`.** Different cause, different evidence (another tag keeps the old figure there; here nothing does), different wording ("not comparable" against "may not be"). Two codes keep the app's ranking simple.
- **Flag every recast, however small.** 0.5% is the threshold the meaning-change scan already uses; `largest_move` lets the app grade it (Walmart's −0.7% quarter recasts are real reclassifications, but minor).

## Files

`domains/fundamentals/facts.py`, `domains/analysis/reported.py`, `tests/analysis/test_series_recast.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q2 (a margin over five years) and Q1 when a few quarters are shown together; closes the gap the brief names under "Notes on a series" ("the engine does not flag that yet (#297 item 13)").

- **Added:** note code `series_mixes_vintages` on `reported_series(...).notes`, params as in Step 2. Listed after any `series_mixes_meanings`.
- **Nothing renamed or removed; no value changes.** `reported_period` is untouched.
- For the app (product lead): series notes are their own tier, above the chart, read before any figure's notes: `series_mixes_meanings` first, then `series_mixes_vintages` (in `recast_on` order, as given), then each figure's notes in the brief's usual order; a year's `changed` flag stays last in its panel, and this note now explains it. Mark the break between `before_periods` and the rest, and any `mixed_periods`, with a mark or pattern, not colour alone. Suggested Spanish (product lead and professor): "En esta serie no todos los ingresos están sobre la misma base: el {form} presentado el {fecha} {redujo|aumentó} cifras de ingresos ya publicadas (una {baja|alza} de hasta {movimiento}){, entre ellas {moved}}; {before} siguen con las cifras presentadas antes, que no tienen una versión posterior en los datos etiquetados; {after} son las de ese {form} o posteriores. {mixed} combina cifras de antes y después de ese cambio. Los ingresos y los márgenes calculados sobre ellos podrían no ser comparables de un lado al otro. Warren no sabe por qué cambiaron (por ejemplo, un negocio separado, vendido o reincorporado, una norma contable nueva, un cambio de presentación o una corrección); el {form} lo explica." Dates and percentages in the region's format (28 feb 2018; 8,2 %). Never "reexpresado" (IAS 8.42 error correction; IAS 29 inflation).

## Limits

- Only revenue, as the other series note.
- 0.5% is a detection threshold, not a judgment of materiality (SEC SAB 99 warns against a purely numerical test); `largest_move` is given so the reader can judge size.
- "Before" means no later version in the filings' tagged data (XBRL company facts). A 10-K's untagged five-year summary may restate older years; the engine cannot see it.
- The engine does not know why figures moved; the text says so.
- A recast is dated by the filing that first moved figures; a later filing that moves them again is its own recast and note.
- A recast is counted only when its filing's top tag for the period is the tag the series shows (design review, analyst); a restatement filed only under a lower-ranked tag is not seen, as the concept map already says for `latest` mode.
- Each filing is compared with the one before, so a figure moved in small steps of under 0.5% never adds up to a note (analyst).
- The walk does not skip a version filed with a flipped sign (#280); no revenue version has one today. Within one filing, two rows of the same tag and period with different values are ordered by read order (`_best_tag_rows`); none exists for revenue today (analyst).
- P&G's #322 tagging error shows as two large recasts until #322 is decided.
- Growth on a single period across a recast (Apple FY2009Q4 against FY2008Q4, #297 comment of nov.10.2026) is not noted here: this is the series note only.

## Design review (nov.11.2026)

- **Analyst (NO-GO, five blockers, all fixed).** 1 and 4: the walk and the side used each filing's own top tag and any tag, while the series shows the top tag across all filings; now a recast counts only on the shown tag, and the side is judged by the shown tag's filing dates. 2: Walmart's quarter notes (10-Ks tagging net sales, 10-Qs total revenues) were false; gone. 3: P&G's notes contradicted the figures shown; they now follow them (the −66% note stays until #322). 5: test added (a 10-K giving a year only under a lower-ranked tag is no recast). Ideas taken: Limits on small steps, flipped signs and read order; "including" only names periods the recast moved on the shown tag. Walmart's quarters mixing net sales (Q4, from the 10-K year) and total revenues is filed as its own issue.
- **Professor (NO-GO, one blocker, fixed).** "Never filed again" may be false: a 10-K's five-year summary can restate older years without tagging them (Exxon's 2017 summary for 2013–2014). The text now says "with no later version in the filings' tagged data", and Limits say so. Taken: a wider list of causes (separated, sold or brought back; a change in presentation), "lowered" or "raised", decimal comma in Spanish, 0.5% as a detection threshold (SAB 99), the SEC's five-year relief for ASC 606 cited in the Problem.
- **Product lead (GO).** Taken: the order rule (by `recast_on`), series notes as their own tier above the chart (meaning first, then this note, then figure notes), a Spanish clause for the after and mixed periods, "podrían", "siguen con las cifras", and "Warren no sabe por qué … el {form} lo explica" instead of "las presentaciones no dicen por qué". The brief's series paragraph is the front-end's edit after merge.
- **Explainer.** Answered in Step 1 and Step 2: a period's first filing is never a recast; "keeps its sign" is the value's sign; `largest_move` for years uses periods of 300 days or more; a series all "mixed" is not split; the fixture's 2019 10-Qs recast the comparative quarters; "Where the work stopped" removed (Step 3 is complete).
