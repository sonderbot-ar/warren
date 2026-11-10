# Backlog #310: one label per year, a check that says so, and the filing's own year kept

Issue: https://github.com/sonderbot-ar/warren/issues/310 · Branch `backlog-310-fiscal-label-check` · Status: PR open (nov.10.2026); Steps 0–4 built

## Problem

Three follow-ups from the review of #306 (v0.9.51, Walmart's fiscal-year labels).

1. **Two years share one label.** In `financial_facts`, as of the snapshot of nov.10.2026:

   | Company | Period | Revenue (million USD) | Label today | Should be |
   |---|---|---|---|---|
   | Apple | 2007-09-30 to 2008-09-27 | 32,479 first reported, 37,491 latest (restated in the 10-K/A of 2010-01-25) | FY2009 | FY2008 |
   | Apple | 2008-09-28 to 2009-09-26 | 36,537 first reported, 42,905 latest | FY2009 | FY2009 |
   | Caterpillar | 2007-01-01 to 2007-12-31 | 44,958 and 41,962 (revenue and sales tags) | FY2009 | FY2007 |
   | Caterpillar | 2009-01-01 to 2009-12-31 | 32,396 and 29,540 (revenue and sales tags) | FY2009 | FY2009 |

   Apple has no FY2008 at all; Caterpillar's 2007 sits under FY2009. A reader that keys on the label alone gets two years under one name.

   **Cause.** `ingest._primary_periods` takes a filing's own period end as the end date most of its facts share. Three annual filings carry more facts at the year before their own: Apple's 10-K for fiscal 2009 (0001193125-09-214859, filed 2009-10-27) and its 10-K/A (0001193125-10-012091, filed 2010-01-25), and Caterpillar's 10-K for 2009 (0000018230-10-000092, filed 2010-02-19), whose most common end is 2007-12-31. Those filings say `fy` 2009 and `fp` FY, so the filing calendar (`ingest.build_filing_calendar`: each filing's own period end, named by the filing's `fy` and `fp`; renumbered by #306 when consecutive year ends skip a number) names the older year end FY2009, and every fact ending then takes that label. The real 2009 year end is not in the calendar, so `place_period_end` places its facts a whole number of years from the closest calendar entry with the same day of year (Apple's 2010-09-25 FY2010, one year back), and they also land on FY2009.

2. **No check that a label is used once.** Nothing in the ingest notices two different period ends under one (fiscal year, period). It kept item 1 silently for years.

3. **The filing's own year is not stored.** `financial_facts.fiscal_year` is Warren's label from the filing calendar. What each filing called its own period (`fy`, `fp` in the company facts) is thrown away, so a period renumbered by #306 cannot be traced back to what the filing said, and the ingest prints only a count of renumbered entries.

## Plan

**Step 0. This doc.**

**Step 1. A filing's own period is its latest full-length period.**

- `_primary_periods` takes a filing's own period end as the **latest end among its duration facts whose length matches the form**: 12 months (350–380 days) for a 10-K or 10-K/A; 3, 6 or 9 months (80–100, 170–200, 260–290 days) for a 10-Q or 10-Q/A; ignoring any fact whose `end` is after the filing's `filed` date (an end on the filing day is kept; such facts are already rejected as data errors). The lengths are the 3, 6, 9 and 12-month spans of `MONTHS_BY_DAYS` (84–98, 175–190, 266–282, 357–378 days), the same ones `label_fact` uses, so an own period is never a length the labels would drop (analyst, professor). A comparative always ends before the filing's own period, because Regulation S-X Rule 3-02 has a 10-K present the current year and earlier ones, so the latest full-length period is the filing's own; the check in Step 2 is the backstop if a filing ever breaks this.
- Any filing with no such duration (instants only, or a 10-K with only quarters) falls back to the old majority rule, unchanged and without the filing-date filter. The analyst found no filing among the eight companies that falls back.
- On the eight companies' company facts (cached nov.10.2026), the new rule changes the own period of exactly the three filings above (Apple 70, Microsoft 69, Walmart 70, Coca-Cola 70, P&G 70, J&J 70, Caterpillar 69, Exxon 69 filings checked, from `data/raw/edgar/companyfacts/`) and no other: Apple's two to 2009-09-26, Caterpillar's to 2009-12-31. An earlier draft without the filing-date filter also moved one Walmart and two P&G 10-Ks to a year end after their filing date (a mis-dated fact); the filter is why it doesn't.
- Tests (`tests/fundamentals/test_ingest.py`): a 10-K with more facts at the prior year end than at its own (Apple-like) is placed at its own year end; a 10-Q likewise at its quarter; a fact dated after the filing is ignored; a filing with only instants keeps the majority rule; the calendar for an Apple-like history labels the prior year FY2008 and its own year FY2009.
- Exit: the suite passes.

**Step 2. A check that each label names one period.**

- `ingest.label_collisions(rows)` groups the labelled rows (leaving out cover-page `dei` facts, which are dated near the filing day and take the filing's own label by design: with them, 382 false collisions on the eight companies; analyst) by (fiscal year, fiscal period, instant or duration) and returns each group whose period ends differ by more than `SAME_END_TOLERANCE_DAYS` (7 days; 52/53-week years move an end by a few days), as `LabelCollision(fiscal_year, fiscal_period, kind, ends)`. Facts carry the labels Q1–Q4 (3 months), H1, M9 and FY; durations of different length never share one, so the group is by label and kind, not by start.
- `ingest.year_breaks(calendar)`: two fiscal year ends one year apart in the calendar whose fiscal years are not consecutive (a year left without a name, as Apple's FY2008 was, or a renumbering #306 declined), as `YearBreak` (analyst idea 5).
- `IngestResult.label_collisions` and `year_breaks` hold them; the `ingest` command prints each by name ("label names two periods: FY2009 duration: 2008-09-27, 2009-09-26") and returns exit code 1 when any company has one, so a collision is never silent. Rows are still stored as labelled: the label is a name, values and dates are unaffected, and failing the whole ingest would block every other company's new filings.
- Tests: two year ends under one label are reported; ends within the tolerance, an instant beside a duration, cover facts and unlabelled rows are not; the clean fixture has none; a year skipped between year ends one apart is a break, two years apart is not; the command names the collision and exits 1, and exits 0 when clean.
- The app never runs the ingest, so the exit code only affects the team's runs; with 0 problems on the eight companies, `ingest --all` keeps exiting 0.
- Real data: before Step 1, Apple and Caterpillar report FY2009 (duration and instant) each; after it, all eight companies report 0 collisions and 0 year breaks.
- Exit: the suite passes; 0 collisions on all eight companies.

**Step 3. Keep each filing's own label beside Warren's.**

- Migration `0022_filing_labels.sql`: table `filing_labels` (not `filing_periods`, which is already a function in `ingest.py`; analyst) with one row per 10-K, 10-Q or amendment of a company: `cik`, `accession_no`, `form`, `filed_at`, `period_end` (its own period, Step 1; null for a filing with no us-gaap facts, such as Coca-Cola's cover-only 10-Q/A 0000021344-24-000019; analyst), `filed_fiscal_year` and `filed_fiscal_period` (the SEC's `fy` and `fp` tags for the filing, exactly as given, which can differ from the company's own name for the year: Apple's 10-K text calls the year ending September 2008 "2008"; front-end lead), `fiscal_year` and `fiscal_period` (Warren's label for that end from the filing calendar, null if it can't be placed), primary key (`cik`, `accession_no`). `financial_facts` already carries `accession_no`, so any stored figure joins to its filing's row. `fiscal_period` here is `FY` or `Q1`–`Q3` (a filing's own period, the calendar's quarters), as `fp` is; the H1 and M9 labels exist only on facts.
- The ingest replaces a company's rows in the same transaction as its facts (the calendar is rebuilt from all filings on each ingest, as the labels already are).
- `IngestResult.renumbered` becomes a list of `Renumbered(end, filed_label, label)` (a date and two labels such as `FY2013` or `FY2013Q3`; printed `2014-01-31 FY2013 -> FY2014`); the command prints the count as before and then each one by name, so the printed count line is unchanged.
- `renumbered_entries` returns the list (its only caller is the ingest; its test changes from a count to the list).
- Tests: the migration creates the table and keeps stored facts (`tests/shared_kernel/test_migration_0022.py`); the migration lists in older tests gain 22 (`test_llm_variants`, `test_calls`, `test_store`, `test_state_telemetry`, `test_migration_0017`, `0019`, `0020`, `0021`); ingest stores one row per filing with both labels; Walmart-like fixture rows show `filed_fiscal_year` 2013 and `fiscal_year` 2014 for the year ending January 2014; a cover-only 10-Q/A gets a row with no own period; re-ingest replaces, not duplicates.
- Exit: the suite passes.

**Step 4. Re-label the stored data and check nothing else moved.**

- After `python -m shared_kernel.snapshot restore --dir /mnt/project-files/warren-data/`, `python -m domains.fundamentals ingest --all` from the cached company facts (no download needed; a refresh is not part of this item). Expected: Apple's facts ending 2008-09-27 (and its quarters placed from that end) move from FY2009 to FY2008; Caterpillar's ending 2007-12-31 from FY2009 to FY2007; nothing else moves; 0 collisions; values, dates and filings unchanged (same facts, same count).
- Check: labels before and after for every fact of the eight companies, listed by company and old → new label.
- `python -m domains.analysis reproduce --all`: every stored run reproduces to the cent (runs start in 2019 and read history from FY2016 on, far after the moved years).
- `python -m domains.fundamentals report --all`: no new unexplained gap.
- `reported_period` for Apple FY2008 now answers (it failed: no FY2008); Caterpillar FY2007 answers with 2007's figures.
- `python -m shared_kernel.snapshot save --dir /mnt/project-files/warren-data/` (the labels changed and the new table is filled).
- Exit: the checks above hold, written into this doc.

## Point in time

Labels name a period; they are not information about its value. The own-period rule reads only a filing's own facts. No value, period end or filing date changes, so nothing becomes visible earlier. `filing_labels` stores what each filing said, with its accession; it has no date of its own because each row is the filing itself and joins to `financial_facts.filed_at` through the accession.

## Alternatives considered

- **Mark the duplicate and leave the label (the issue's "visible flag").** The label is simply wrong: Apple's 10-K text calls the year ending September 2008 "2008". Fixing the cause gives every company one name per year; the check in Step 2 stays as the flag for anything that slips through.
- **Use the cover page's document period end (`dei:DocumentPeriodEndDate`).** The SEC's company facts API does not carry it (only a few `dei` facts such as shares outstanding and public float), so it would need each filing's own XBRL instance: a new source and many downloads for three filings.
- **A per-filing override list.** Works for three filings but must be maintained by hand; the length rule is general (Decision 11: companies are data, rules are code).
- **Store the filing's `fy` on every fact.** For a comparative, the filing's `fy` describes the filing, not the fact's period, so it would read as a second, conflicting label on most rows. One row per filing, joined by accession, says exactly what the filing named and nothing more.
- **Fail the ingest on a collision.** Stops new filings for a naming problem that leaves values intact; the exit code and the printed list make it loud without blocking.

## Files

- `domains/fundamentals/ingest.py`: `_primary_periods` (own period by length), `label_collisions`, `LabelCollision`, `year_breaks`, `YearBreak`, `Renumbered`, `FilingLabel`, `filing_labels`, `IngestResult.label_collisions`, `year_breaks`, `filing_labels` and `renumbered` (a list), storing `filing_labels`.
- `domains/fundamentals/__main__.py`: prints collisions and renumbered periods; exit code 1 on a collision.
- `shared_kernel/migrations/0022_filing_labels.sql`.
- Tests: `tests/fundamentals/test_ingest.py`, `tests/shared_kernel/test_migration_0022.py`, the migration lists in older tests.
- `docs/designs/backlog-310-fiscal-label-check.md`: this doc. At merge, a row in `docs/versions.md` and an entry in `docs/team-sync.md`; `docs/build-plan.md` is unchanged (a backlog item has no milestone row).

## Product impact

- **Brief Q1 and Q2 (reported figures and five-year series).** Apple's year ending September 2008 is now FY2008 (it had no FY2008 and two FY2009s); Caterpillar's 2007 is FY2007 (was FY2009). A series for Apple over 2006–2010 now answers year by year with Apple's own names, and Caterpillar's FY2009 is only 2009. Only those labels move: no value, date or filing changes, no field is renamed or removed.
- **Runs and everything after them (Q3–Q15):** unchanged: all 903 stored runs reproduce to the cent after the re-label (Step 4); runs start in 2019.
- **New, engine side only:** the table `filing_labels` (the SEC's `fy` tag for each filing, beside Warren's label). Nothing in `reported_period` or `reported_series` changes. It stays off the reported view: the SEC's tag is not always the company's own name for the year, so it must not be shown as "the filing called it" (front-end lead); the front-end files a request if a screen needs it.
- **Language:** none added for students. The ingest prints in English for the team, and its exit code has no effect on the app.

## Results on the stored data (Step 4, nov.10.2026)

Snapshot of nov.10.2026 (`warren-20261110T153650Z`), re-ingested from the cached company facts, as of 2026-11-09.

- **Labels moved, and nothing else.** 33,490 facts before and after, same ids; every value, period, filing and filing date unchanged. Moved: Apple's facts ending 2008-09-27 (35 durations, 20 balances) FY2009 → FY2008; Caterpillar's ending 2007-12-31 (12 durations, 6 balances) FY2009 → FY2007. No quarter label moved (Apple's three-month quarters were already placed from the right neighbours), so Apple FY2008Q4 and Caterpillar's 2009 quarters keep their names; the sign note on Caterpillar's Q2 2009 cost of revenue keeps its period. Walmart's 19 renumbered entries are as in v0.9.51, now listed by name.
- **Checks.** 0 label collisions and 0 year breaks on all eight companies (before Step 1: Apple and Caterpillar FY2009, duration and instant each). `filing_labels`: 558 filings; 20 where the SEC's `fy` differs from Warren's year, all Walmart's renumbered years; 1 with no own period (Coca-Cola's cover-only 10-Q/A).
- **`reported_period` revenue, before → after** (million USD):

  | Period | Before | After |
  |---|---|---|
  | Apple FY2008 | refused (no FY2008) | 2007-09-30 to 2008-09-27: 37,491 latest, 32,479 first reported, `changed`; growth +52.5% on FY2007's 24,578 |
  | Apple FY2009 | 42,905 latest, 36,537 first; growth not computed (no prior year) | same figures; growth +14.4% |
  | Apple FY2008Q4 | refused | 7,895 (2008-06-29 to 2008-09-27), not changed |
  | Apple FY2009Q4 | 12,207 latest, 9,870 first; growth not computed | same; growth +54.6%, with `uses_changed_line` and `uses_one_basis_line` |
  | Caterpillar FY2007 | refused | 44,958 (2007) |
  | Caterpillar FY2008 | 51,324; growth not computed | same; growth +14.2% |
  | Caterpillar FY2009, FY2010, 2009 quarters | unchanged | unchanged |

  Apple's FY2007 to FY2009 revenue is restated (the 10-K/A of 2010-01-25 changed how iPhone sales are recognised), while its FY2008 quarters were never refiled. So Apple FY2009Q4 growth compares a restated quarter with an unrestated one: +54.6% as computed, far above what the two quarters would show on one basis (the restated FY2008Q4 is not in Warren's data). The figure carries `uses_changed_line` and `uses_one_basis_line`, but nothing yet says the two quarters sit on different bases; that is #297 item 13 (a series or growth across restated and unrestated periods), noted there.
- `python -m domains.analysis reproduce --all`: 903 of 903 runs reproduce to the cent. `python -m domains.fundamentals report --all`: 0 unexplained gaps for every company.

## Design review (nov.10.2026)

Explainer, analyst, professor, and the front-end lead on Product impact. Professor GO; analyst: two blockers, both accepted; no other blockers.

- Analyst 1 (blocker: cover-page facts would make 382 false collisions): accepted; `dei` facts are left out, with a test.
- Analyst 2 (blocker: a filing with no us-gaap facts has no own period): accepted; it gets a row with `period_end` null, with a test (Coca-Cola's cover-only 10-Q/A).
- Analyst 3 (idea: a 10-K transition report after a change of year end has no 12-month own period, so the rule would pick the prior full year): none of the eight has one; filed as a backlog issue with the guard the analyst suggested.
- Analyst 4 and professor suggestion 1 (two sets of day ranges): accepted; one set, `MONTHS_BY_DAYS`. The same three filings move and no other.
- Analyst 5 (a year with no name and a shifted run go unseen): accepted as `year_breaks`.
- Analyst 6 (name clash with the function `filing_periods`): accepted; the table is `filing_labels`.
- Analyst 7 (print filings whose SEC `fy` differs but were not renumbered): the stored data has none outside Walmart's renumbered years; filed with idea 3.
- Professor suggestion 2 (cite Reg S-X 3-02, Step 2 as backstop): accepted in Step 1. Ideas: the Compustat contrast goes in the lesson; the exit code on cloud runs is answered in Step 2; a side-panel line is left to the front-end.
- Front-end lead 1–3 (quarters, before/after answers, note periods): answered in Results (no quarter moved; the answers table; the Caterpillar sign note keeps its period). Idea 4 (the SEC's `fy` is not the company's name): accepted, reworded, kept off the reported view. Ideas 5–6: done.
- Explainer gaps: fallback, filing date, tolerance, label sets, the calendar rule, the moved quarters, restore and snapshot commands, the Renumbered fields, the test files, the accession join and the garbled Files line are answered in the text above. Gap 16 (how `reported_period` picks a filing): unchanged by this item; it reads facts by label and period as before (`docs/designs/backlog-290-one-basis-reported.md`).

## Where the work stopped

- nov.10.2026: Steps 0–4 built, data re-labelled and checked; PR next, then the gatekeeper.
