# Backlog #310: one label per year, a check that says so, and the filing's own year kept

Issue: https://github.com/sonderbot-ar/warren/issues/310 · Branch `backlog-310-fiscal-label-check` · Status: In progress (nov.10.2026)

## Problem

Three follow-ups from the review of #306 (v0.9.51, Walmart's fiscal-year labels).

1. **Two years share one label.** In `financial_facts`, as of the snapshot of nov.10.2026:

   | Company | Period | Revenue (million USD) | Label today | Should be |
   |---|---|---|---|---|
   | Apple | 2007-09-30 to 2008-09-27 | 32,479 and 37,491 (two vintages) | FY2009 | FY2008 |
   | Apple | 2008-09-28 to 2009-09-26 | 36,537 and 42,905 | FY2009 | FY2009 |
   | Caterpillar | 2007-01-01 to 2007-12-31 | 44,958 and 41,962 | FY2009 | FY2007 |
   | Caterpillar | 2009-01-01 to 2009-12-31 | 32,396 and 29,540 | FY2009 | FY2009 |

   Apple has no FY2008 at all; Caterpillar's 2007 sits under FY2009. A reader that keys on the label alone gets two years under one name.

   **Cause.** `ingest._primary_periods` takes a filing's own period end as the end date most of its facts share. Three 10-Ks carry more facts at the year before their own: Apple's 10-K for fiscal 2009 (0001193125-09-214859, filed 2009-10-27) and its 10-K/A (0001193125-10-012091, filed 2010-01-25), and Caterpillar's 10-K for 2009 (0000018230-10-000092, filed 2010-02-19), whose most common end is 2007-12-31. Those filings say `fy` 2009 and `fp` FY, so the filing calendar names the older year end FY2009, and every fact ending then takes that label. The real 2009 year end is not in the calendar, so its facts are placed a whole year from a neighbour and also land on FY2009.

2. **No check that a label is used once.** Nothing in the ingest notices two different period ends under one (fiscal year, period). It kept item 1 silently for years.

3. **The filing's own year is not stored.** `financial_facts.fiscal_year` is Warren's label from the filing calendar. What each filing called its own period (`fy`, `fp` in the company facts) is thrown away, so a period renumbered by #306 cannot be traced back to what the filing said, and the ingest prints only a count of renumbered entries.

## Plan

**Step 0. This doc.**

**Step 1. A filing's own period is its latest full-length period.**

- `_primary_periods` takes a filing's own period end as the **latest end among its duration facts whose length matches the form**: 12 months (350–380 days) for a 10-K or 10-K/A; 3, 6 or 9 months (80–100, 170–200, 260–290 days) for a 10-Q or 10-Q/A; ignoring any fact that ends after the filing date (those are already rejected as data errors). A comparative always ends before the filing's own period, so the latest full-length period is the filing's own.
- Only when a filing has no such duration (instants only, as in some test fixtures) does the old majority rule apply, unchanged.
- On the eight companies' company facts (cached nov.10.2026), the new rule changes the own period of exactly the three filings above (70, 69, 70, 70, 70, 70, 69, 69 filings checked) and no other: Apple's two to 2009-09-26, Caterpillar's to 2009-12-31. An earlier draft without the filing-date filter also moved one Walmart and two P&G 10-Ks to a year end after their filing date (a mis-dated fact); the filter is why it doesn't.
- Tests (`tests/fundamentals/test_ingest.py`): a 10-K with more facts at the prior year end than at its own (Apple-like) is placed at its own year end; a 10-Q likewise at its quarter; a fact dated after the filing is ignored; a filing with only instants keeps the majority rule; the calendar for an Apple-like history labels the prior year FY2008 and its own year FY2009.
- Exit: the suite passes.

**Step 2. A check that each label names one period.**

- `ingest.label_collisions(rows)` groups the labelled rows by (fiscal year, fiscal period, instant or duration) and returns each group whose period ends differ by more than `SAME_END_TOLERANCE_DAYS` (52/53-week years move an end by a few days), as `LabelCollision(fiscal_year, fiscal_period, kind, ends)`. Durations of different length can share a label legitimately only through the existing labels (`Q2` 3 months, `H1` 6 months), so the group is by label and kind, not by start.
- `IngestResult.label_collisions` holds them; the `ingest` command prints the count and each collision by name ("FY2009 duration: 2008-09-27, 2009-09-26"), and returns exit code 1 when any company has one, so a collision is never silent. Rows are still stored as labelled: the label is a name, values and dates are unaffected, and failing the whole ingest would block every other company's new filings.
- Tests: two year ends under one label are reported, ends within the tolerance are not, an instant and a duration with the same label and end are not a collision, the clean fixture has none; the command exits 1 on a collision.
- Real data: after Step 1, all eight companies report 0 collisions (before Step 1: Apple and Caterpillar report theirs).
- Exit: the suite passes; 0 collisions on all eight companies.

**Step 3. Keep each filing's own label beside Warren's.**

- Migration `0022_filing_periods.sql`: table `filing_periods` with one row per 10-K, 10-Q or amendment of a company: `cik`, `accession_no`, `period_end` (its own period, Step 1), `filed_fiscal_year` and `filed_fiscal_period` (`fy` and `fp` exactly as the filing gives them), `fiscal_year` and `fiscal_period` (Warren's label for that end from the filing calendar, null if it can't be placed), primary key (`cik`, `accession_no`). Facts join it on `accession_no`, so any stored figure can be traced to what its filing called its own period. `fiscal_period` here is `FY` or `Q1`–`Q3` (a filing's own period), as `fp` is.
- The ingest replaces a company's rows in the same transaction as its facts (the calendar is rebuilt from all filings on each ingest, as the labels already are).
- `IngestResult.renumbered` becomes the list of renumbered filing-calendar entries (`end`, `filed_label`, `label`, e.g. `2014-01-31 FY2013 → FY2014`); the command prints the count as before and then each one by name, so the printed count line is unchanged.
- `renumbered_entries` returns the list (its only caller is the ingest; its test changes from a count to the list).
- Tests: the migration creates the table and keeps stored facts (`tests/shared_kernel/test_migration_0022.py`); the migration lists in older tests gain 22; ingest stores one row per filing with both labels; Walmart-like fixture rows show `filed_fiscal_year` 2013 and `fiscal_year` 2014 for the year ending January 2014; re-ingest replaces, not duplicates.
- Exit: the suite passes.

**Step 4. Re-label the stored data and check nothing else moved.**

- `python -m domains.fundamentals ingest --all` from the cached company facts (no download needed; a refresh is not part of this item). Expected: Apple's facts ending 2008-09-27 (and its quarters placed from that end) move from FY2009 to FY2008; Caterpillar's ending 2007-12-31 from FY2009 to FY2007; nothing else moves; 0 collisions; values, dates and filings unchanged (same facts, same count).
- Check: labels before and after for every fact of the eight companies, listed by company and old → new label.
- `python -m domains.analysis reproduce --all`: every stored run reproduces to the cent (runs start in 2019 and read history from FY2016 on, far after the moved years).
- `python -m domains.fundamentals report --all`: no new unexplained gap.
- `reported_period` for Apple FY2008 now answers (it failed: no FY2008); Caterpillar FY2007 answers with 2007's figures.
- Save a snapshot (the data changed).
- Exit: the checks above hold, written into this doc.

## Point in time

Labels name a period; they are not information about its value. The own-period rule reads only a filing's own facts. No value, period end or filing date changes, so nothing becomes visible earlier. `filing_periods` stores what each filing said, with its accession; it has no date of its own because each row is the filing itself and joins to `financial_facts.filed_at` through the accession.

## Alternatives considered

- **Mark the duplicate and leave the label (the issue's "visible flag").** The label is simply wrong: Apple's 10-K text calls the year ending September 2008 "2008". Fixing the cause gives every company one name per year; the check in Step 2 stays as the flag for anything that slips through.
- **Use the cover page's document period end (`dei:DocumentPeriodEndDate`).** The SEC's company facts API does not carry it (only a few `dei` facts such as shares outstanding and public float), so it would need each filing's own XBRL instance: a new source and many downloads for three filings.
- **A per-filing override list.** Works for three filings but must be maintained by hand; the length rule is general (Decision 11: companies are data, rules are code).
- **Store the filing's `fy` on every fact.** For a comparative, the filing's `fy` describes the filing, not the fact's period, so it would read as a second, conflicting label on most rows. One row per filing, joined by accession, says exactly what the filing named and nothing more.
- **Fail the ingest on a collision.** Stops new filings for a naming problem that leaves values intact; the exit code and the printed list make it loud without blocking.

## Files

- `domains/fundamentals/ingest.py`: `_primary_periods` (own period by length), `label_collisions`, `LabelCollision`, `Renumbered`, `IngestResult.label_collisions` and `renumbered` (a list), storing `filing_periods`.
- `domains/fundamentals/__main__.py`: prints collisions and renumbered periods; exit code 1 on a collision.
- `shared_kernel/migrations/0022_filing_periods.sql`.
- Tests: `tests/fundamentals/test_ingest.py`, `tests/shared_kernel/test_migration_0022.py`, the migration lists in older tests.
- `docs/designs/backlog-310-fiscal-label-check.md`: this doc. At merge, `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` is unchanged (a backlog item).

## Product impact

- **Brief Q1 and Q2 (reported figures and five-year series).** Apple's year ending September 2008 is now FY2008 (it had no FY2008 and two FY2009s); Caterpillar's 2007 is FY2007 (was FY2009). A series for Apple over 2006–2010 now answers year by year with Apple's own names, and Caterpillar's FY2009 is only 2009. Only those labels move: no value, date or filing changes, no field is renamed or removed.
- **Runs and everything after them (Q3–Q15):** unchanged; runs start in 2019. To be confirmed by the reproduce check in Step 4.
- **New, engine side only:** the table `filing_periods` (what each filing called its own period, beside Warren's label). Nothing in `reported_period` or `reported_series` changes; if the side panel later wants "the filing called this fiscal 2013", it can be added on request as a field there.
- **Language:** none added for students. The ingest prints in English for the team.

## Where the work stopped

- nov.10.2026: design doc written; review next.
