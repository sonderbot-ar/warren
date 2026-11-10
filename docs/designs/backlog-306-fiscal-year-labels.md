# Backlog #306: a company that changed how it numbers its fiscal years

Issue: https://github.com/sonderbot-ar/warren/issues/306 · Branch `backlog-306-fiscal-year-labels` · Status: in review (PR to come).

## Problem

`reported_period(conn, "WMT", "FY2014", D)` fails ("revenue not reported by the as-of date"), so any Walmart series holding FY2014 is refused and brief Q2 for Walmart over 2012–2016 cannot be answered.

Cause, from Walmart's company facts on EDGAR (the `fy` and `fp` of each filing's own period, which `ingest.build_filing_calendar` uses to name fiscal years):

| Filing's own period ends | Filed | `fy` in the filing | Walmart's own name |
|---|---|---|---|
| 2013-01-31 (10-K) | 2013-03-26 | 2012 | fiscal 2013 |
| 2013-04-30 … 2013-10-31 (10-Qs) | 2013 | 2013 | fiscal 2014 Q1–Q3 |
| 2014-01-31 (10-K) | 2014-03-21 | 2013 | fiscal 2014 |
| 2014-04-30 (10-Q) | 2014-06-06 | **2015** | fiscal 2015 Q1 |
| 2015-01-31 (10-K) | 2015-04-01 | 2015 | fiscal 2015 |

Up to January 2014 Walmart's filings numbered a fiscal year by the calendar year it starts in; from the 10-Q of 2014-06-06 on, by the year it ends in (its own name, as in its annual reports). The filing calendar took each filing's number as given, so every Walmart period ending from July 2009 to January 2014 was labelled one year lower than Walmart names it, and no period was labelled FY2014. A year-earlier comparison across the change failed too: FY2015 and FY2015Q1–Q4 had no revenue growth.

The same check on the other seven companies' company facts (fetched nov.10.2026) finds no other break between consecutive year ends. Apple and Caterpillar each have one old 10-K whose own period sits two or three years before the next year end (an odd majority end in a 10-K of 2009); those are not consecutive year ends and are left alone. Procter & Gamble (June) and Microsoft (June) are consistent.

## Plan

**Step 0. This doc.**

**Step 1. Continuous year numbers in the filing calendar.**

- `ingest._continuous_year_numbers(entries)`, applied at the end of `build_filing_calendar` to the calendar as filed (`_raw_calendar`). Year ends are the calendar's quarter-4 entries (a filing's own fiscal year end; a year with no 10-K has none). Walking them from the newest back, two year ends one year apart (365.25 days within `YEAR_DRIFT_TOLERANCE_DAYS`, so 52/53-week years pass) must carry consecutive fiscal years. When they don't, the older one is shifted to meet the newer one's number (after the newer one's own shift, so shifts chain; a shift can be up or down and by more than one year).
- The newer numbering must hold for at least two consecutive year ends: the newer year end and the one after it, one year apart and consecutive as filed. Otherwise the break is left as filed, so one wrong `fy` in the newest 10-K cannot renumber a whole history (analyst). Walmart's newer numbering holds for twelve year ends.
- Which entries move: an entry takes the shift of the first year end on or after its own end (within `SAME_END_TOLERANCE_DAYS`), so a quarter moves with the fiscal year it belongs to; entries after the newest year end never move.
- Across year ends further apart (a hole in the calendar, a change of year end) nothing says the numbering changed, so the shift accumulated so far carries on unchanged; with no shift, nothing moves.
- Periods older than the oldest calendar entry (comparatives in the first 10-Ks) are placed a whole number of years from a renumbered entry by `place_period_end`, so they move with it: Walmart's years ending January 2008 and 2009 become FY2008 and FY2009 (were FY2007 and FY2008).
- `IngestResult.renumbered` counts the calendar entries renumbered and the `ingest` command prints it ("69 filing periods (19 renumbered)" for Walmart), so a renumbering is never silent (analyst, professor).
- `label_fact` and `filing_periods` place every fact against this calendar, so comparatives in later filings take the same labels.
- Only labels move. Values, dates, filings and the facts kept are unchanged (`UPSERT_FACT` already updates only the labels on re-ingest).
- Tests (`tests/fundamentals/test_ingest.py`): a Walmart-like calendar is renumbered (FY2013 → 2014 and its quarters with it, the later years unchanged) and a comparative year, a comparative fourth quarter and an older quarter are labelled to match; the test company's consecutive calendar is unchanged; year ends two years apart keep their labels; a shift carries across an older gap; one wrong year in the newest filing (2021, 2022, 2025) leaves the history alone; a numbering that moves down (2013, 2014, 2014, 2015) shifts older years down; `build_filing_calendar` on raw filings with `fy` 2012, 2013, 2015, 2016 gives 2013–2016 and `renumbered_entries` counts 2 (0 for the test company).
- Exit: the suite passes.

**Step 2. Re-label the stored data and check nothing else moved.**

- `python -m domains.fundamentals ingest --ticker WMT` from the stored company facts (no download): 0 new facts, 69 filing periods (19 renumbered), 0 without a fiscal period. Every Walmart period ending on or before 2014-01-31 moves up one year (old label → new: the year ending January 2008 FY2007 → FY2008, … the year ending January 2014 FY2013 → FY2014, and their quarters); periods from February 2014 on keep their labels. Values, dates and filings are unchanged (same rows, same hash of labels and periods as a second re-ingest).
- Results on the snapshot of nov.05.2026, as of 2026-11-09:
  - Walmart's five years FY2012–FY2016 now answer: revenue 446,509 / 468,651 / 476,294 / 485,651 / 482,130 million USD, each Walmart's own figure for that fiscal year.
  - FY2015 revenue growth is now 2.0% (was not computed) and FY2015Q1 0.8% (was not computed); FY2014 growth is 1.6%.
  - `python -m domains.analysis reproduce --all`: 903 of 903 runs reproduce to the cent, before and after.
  - A baseline built fresh (`math_engine.build_inputs`) for Walmart on the 15th of Feb, May, Aug and Nov from 2019 to 2026 (31 dates) is identical before and after: runs start in 2019 and use history from FY2016 on, after the change.
  - Quality report for Walmart: 0 unexplained gaps.

## Point in time

Labels are the period's name, not information about its value. A query as of 2014-03-31 now calls Walmart's year ending January 2014 "FY2014", a number Walmart's filings only used from June 2014; Walmart's 10-K filed 2014-03-21 (accession 0000104169-14-000019) already called it fiscal 2014 in its text. The calendar has always been built from all of a company's filings (placing a comparative needs later entries), and no value or filing date depends on the label, so no figure becomes visible earlier than it was.

## Alternatives considered

- **Relabel in the reported view only.** Runs, the harness and the quality report read the same labels from `financial_facts`; one fix in the calendar keeps them all consistent.
- **Keep the filings' numbering and fill the gap.** Calling Walmart's year ending January 2014 "FY2013" disagrees with Walmart's own annual reports and with every later filing; a student checking against the 10-K would be lost.
- **Compustat's convention.** Compustat, the research database most finance courses use, names a fiscal year ending January to May by the previous calendar year, so Walmart's year ending January 2014 is Compustat's fiscal 2013 (professor). Warren follows the company's own name instead, because a student checks a figure against the company's 10-K, and the SEC's own example of the fiscal-year field is the company's name for its year ("fiscal 2006"; XBRL US, DQC_0006). A student comparing with Compustat will see Walmart one year apart; the lesson says so.
- **A per-company override in a CSV.** Works, but the rule is general (a year number cannot skip or repeat between consecutive year ends) and needs no list to maintain. Companies stay data.

## Files

- `domains/fundamentals/ingest.py`: `_raw_calendar`, `_continuous_year_numbers` (called by `build_filing_calendar`), `renumbered_entries`, `IngestResult.renumbered`.
- `domains/fundamentals/__main__.py`: `ingest` prints the renumbered count.
- `tests/fundamentals/test_ingest.py`: seven tests.
- `docs/designs/backlog-306-fiscal-year-labels.md`: this doc.

## Product impact

- Brief Q1 and Q2: Walmart's FY2014 and any series holding it now answer, and every Walmart period ending on or before 2014-01-31 carries Walmart's own name (one year higher than before: the year ending January 2009 is now FY2009, was FY2008). FY2015's revenue growth and FY2015Q1–Q4's are now computed.
- The skipped-sign notes of v0.9.48 on Walmart's income tax (years ending January 2009 to January 2011 and their fourth quarters) keep their periods and values; their period labels in `params` move up one year with everything else (FY2008 → FY2009 and so on). The brief names those periods by end date, so its text stays correct.
- Q1's latest quarter and every run (Q3–Q8, Q15) are unchanged: the 31 fresh Walmart baselines are identical and all 903 stored runs reproduce.
- Nothing added, renamed or removed in any output; no value changes. A period label the app stored for Walmart before FY2015 (none expected; the app is not built) would now name the next year.
- For the front-end's own later edit: brief Q2's "fiscal-year labels are each company's own" is now true for Walmart's early years too.

## Design review

Explainer, analyst, professor and the front-end lead (Product impact), nov.10.2026. Analyst GO, professor GO; no blockers.

- Analyst 1 (one wrong `fy` in the newest 10-K renumbers the whole history, silently): accepted. The newer numbering must now hold for two consecutive year ends, and the ingest result counts renumbered entries. Tests added.
- Analyst 2 (no check that labels are unique after renumbering; a change of year end with a renumbering): the rule never creates a duplicate; the check belongs with item 3's older problem. Filed as #310.
- Analyst 3 (Apple and Caterpillar each have two years under FY2009 from an odd 10-K in 2009): older than this change and untouched by it. Filed as #310.
- Analyst 4 (point in time): agreed; rows keep period end, value and filing date.
- Professor 1 (Compustat names Walmart's year a year lower): accepted; Alternatives and the lesson say Warren follows the company's own name.
- Professor 2 (cite the 10-K): accepted; accession added.
- Professor 3 (store the filing's own `fy`): the renumbered count is printed now; storing it per fact goes in #310.
- Professor 4 (a tooltip for retailers' fiscal years): front-end idea, left to F2.
- Explainer gaps 1–4 and 6 (which year end a quarter belongs to, entries after the newest year end, chaining and direction, year ends without a 10-K, old and new labels for the range): answered in Step 1 and Step 2. Gap 5 (is the calendar rebuilt as of a date): no; labels are built once from all filings, as before this change, and only names move (Point in time). Gap 7: `place_period_end` handles comparatives older than the oldest entry by whole years; Step 1 says so.
- Front-end lead 1–3 (exact range, the sign notes, latest quarter and runs unchanged): accepted in Product impact.
