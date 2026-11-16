# Backlog #342: no "stale" warning while the annual report is simply not due yet

Issue: https://github.com/sonderbot-ar/warren/issues/342 · Branch `backlog-342-stale-after-q3` · Version v0.9.61, merged nov.12.2026 (PR #348, merge `2d80e3f`).

## Problem

A run warns `fundamentals_stale` when its newest quarter ended more than 135 days before the run's date (`STALE_AFTER`, `domains/analysis/math_engine.py:68`, checked in `_last_actual_quarter`). 135 days fits a quarterly report: a quarter of about 92 days, then 40 days to file the 10-Q (large accelerated filer), then 3 days for a deadline that falls on a weekend or holiday.

After a third quarter the next report is the 10-K, due 60 days after the year ends, so about 152 days after a September 30 quarter end. On the snapshot of nov.10.2026, 12 of the 13 stored `fundamentals_stale` notes are February 15 runs whose last quarter is a fiscal Q3 (CAT 2020, 2022, 2024; JNJ 2020, 2024; KO 2020, 2022, 2024, 2026; XOM 2020, 2022, 2024; 137 to 142 days). Every one of those companies filed its 10-K on time (for example CAT 2024-02-16, XOM 2024-02-28). The warning is false. The 13th, `XOM_2026-10-30_1` (last quarter 2026-03-31, 213 days), is a real gap: Exxon's history ends when it reorganised (`domains/fundamentals/universe.csv`), and it must keep warning.

The lesson for this warning (`domains/analysis/text.py`, `fundamentals_stale`, v0.9.60) already tells the student that the annual report can come about 150 days after the third quarter. The warning should agree with its own lesson.

## The rule (fixed here)

The line depends on which report comes next, read from the newest quarter's fiscal period:

| Newest quarter | Next report | Line | Built from |
|---|---|---|---|
| Q1, Q2 or Q4 | 10-Q | 135 days (unchanged) | 92-day quarter + 40-day 10-Q deadline + 3 days |
| Q3 | 10-K | **161 days** | 98-day fourth quarter + 60-day 10-K deadline + 3 days |

The fourth quarter is taken at 98 days, not 92, because JNJ, a 52/53-week filer, has a 14-week fourth quarter in a 53-week year (FY2015: 2015-09-28 to 2016-01-03 in the database; Q3 end to the 10-K deadline of 2016-03-03 is 158 days). KO's fiscal Q3 can end as early as September 26 (2025: to the 10-K deadline of March 2, 2026 is 157 days), so a 155-day line would still warn falsely on both. (AAPL's 14-week quarter is its Q1, not its Q4; see Known limits.) Deadlines are the large accelerated filer ones (SEC Form 10-Q and Form 10-K, General Instruction A); every company in the universe is one, and the 135-day line already assumed it. The 3 days cover a deadline that moves to the next business day (Exchange Act Rule 0-3).

Both lines stay working rules in `math_engine.py`, now built from named parts so their source is in the code: `STALE_AFTER` (10-Q, 135) and `STALE_AFTER_Q3` (10-K, 161).

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. The rule.** `math_engine.py`: `QUARTER_DAYS = 92`, `LONG_QUARTER_DAYS = 98`, `DEADLINE_10Q = 40`, `DEADLINE_10K = 60`, `DEADLINE_SLACK = 3`; `STALE_AFTER = timedelta(QUARTER_DAYS + DEADLINE_10Q + DEADLINE_SLACK)` (135, unchanged) and `STALE_AFTER_Q3 = timedelta(LONG_QUARTER_DAYS + DEADLINE_10K + DEADLINE_SLACK)` (161). `_last_actual_quarter` picks the line from `last.fiscal_period`; the note's code, params (`last_quarter_end`, `days`, `threshold_days`) and English text keep their shape, and `threshold_days` is the line used (135 or 161).
  Tests (`tests/analysis/test_build_warning_codes.py`): the existing 182-day Q4 case is unchanged (`threshold_days` 135); a last quarter that is Q3 at 138 days gives no note (the CAT 2024 case); a Q3 at 162 days warns with `threshold_days` 161; a Q2 at 136 days still warns with 135. Boundary: exactly 161 days after a Q3 does not warn (the check is "more than").
  Exit: tests pass; changing the Q3 branch back to 135 fails a test.
- **Step 2. The lesson.** `text.py`, `fundamentals_stale`. Both params come from the constants (`days` = `STALE_AFTER.days`, `days_q3` = `STALE_AFTER_Q3.days`), as every lesson's thresholds do; `tests/analysis/test_warning_lessons.py` `THRESHOLDS` gets the new param. The sentence (the lesson tests allow two):
  > "The newest quarter the run uses ended more than 135 days before the run's date (161 after a third quarter, because no quarterly report is filed for the fourth quarter and the annual report that covers it is due 60 days after the year ends, not 40), so the next report should already be out. Warren may be missing a filing, or the company filed late: check the company's list of filings."

  This drops "figures over four months old" (wrong at 161 days) and "60 to 90 days" (90 is for non-accelerated filers; none is in the universe). `reference` names Form 10-Q General Instruction A.1, Form 10-K General Instruction A(2)(a) and Rule 0-3. `warren_rule` stays set ("the 135- and 161-day lines are working rules: …"), so the app keeps showing them as Warren's own rule, not a law.
  Exit: the lesson tests pass and the lesson's numbers come from the constants, not typed twice.
- **Step 3. Real data.** Restore the snapshot (`python -m shared_kernel.snapshot restore`, nov.10.2026, 903 stored runs). For each of the 13 runs with a stored `fundamentals_stale` note, call `runs.rebuild` (in memory; nothing is stored) on `main` and on this branch and compare the notes it returns with the stored one (expected: only `XOM_2026-10-30_1` still warns); `reproduce --all` (numbers do not change: the line only decides a note).
  Exit: 12 of 13 lose the note, XOM 2026-10-30 keeps it, every run reproduces.

**Where the fiscal period comes from.** `last` is the newest quarterly revenue fact in the run's history (`_last_actual_quarter`); its `fiscal_period` is the company's own fiscal-calendar label from `financial_facts`. The analyst checked every company: the last quarter before each 10-K is labelled Q3 (AAPL June/July, MSFT and PG March, WMT October, CAT and XOM September, JNJ and KO September/October), so the rule follows each fiscal year, not the calendar.

**Known limits.** (1) AAPL puts its 53rd week in Q1 (FY2023: 2022-09-25 to 2022-12-31), so in a 53-week year its first 10-Q can be due 138 days after its last quarter; the 135-day line could then warn on a filing made on the deadline. AAPL filed at 132 days, so no stored run is affected; per-company calendars wait for the Phase 2 per-company deadline (Alternatives). (2) If a 10-K is ingested but its fourth quarter can't be derived, the newest quarter stays Q3 and the warning comes 26 days later than under the old line; the gap is bounded. (3) A company that files late under an NT 10-K (Rule 12b-25, 15 more days) still warns, which is right: the run really is working from older figures.

**Stored runs.** Notes are stored with each run (`run_notes`) and are not rewritten; `reproduce` compares assumption rows, not notes (`domains/analysis/runs.py`, `rebuild`). So the 12 stored false notes stay on their old runs, and only runs made after the merge follow the new line. Rewriting stored notes would change stored history for a wording-level fix; not done.

**Point in time.** Nothing new is read; the line uses the newest quarter the run already saw as of its date. **LLMs.** None. **Decision 11.** No source, company or currency change. The deadlines are US SEC ones; a later non-US adapter would bring its own (noted in the code).

## Alternatives considered

- **One line of about 155 days for every quarter** (the issue's second option). Rejected: it would hide a missing 10-Q for three extra weeks on the three quarters where 135 days is right.
- **155 days after a Q3** (92-day quarter). Rejected: KO's fiscal Q3 ended September 26, 2025, so its on-time 10-K could arrive 157 days later; a 14-week fourth quarter must fit.
- **Read the filer status and the exact fiscal year end from the filings** (accelerated vs large accelerated, 52/53-week calendar). Rejected for now: all eight companies are large accelerated filers; the per-company deadline is a Phase 2 item for a wider universe, and the named constants make it a one-place change.
- **Rewrite the 12 stored false notes.** Rejected: stored runs keep what they said when made (the same rule as other note changes, e.g. v0.9.15).

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/text.py`, `tests/analysis/test_build_warning_codes.py`, `tests/analysis/test_warning_lessons.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Design review (nov.12.2026)

Explainer, analyst and professor in parallel, and the product lead on *Product impact*. Analyst GO, professor GO, product lead OK; no blockers kept.

- **Analyst.** Measured every 10-K's lag from the Q3 end, 2019-2026: the worst is KO at 153 days (filed 2021-02-25), then XOM 151, WMT and JNJ 148, CAT 142, PG 129, AAPL 128, MSFT 125, all under 161; the worst 10-Q lag is 132 days (AAPL), under 135. All 12 false notes clear and XOM 2026-10-30 keeps its note. Taken: the 98-day reason rests on JNJ, not KO or AAPL (idea 1); AAPL's Q1 limit is written down (idea 2); the run list in Problem corrected (idea 3); the derived-Q4 edge stated (idea 4).
- **Professor.** Checked Form 10-K General Instruction A(2)(a) (60 days for large accelerated filers). Taken: the lesson sentence is in this doc, says why the third quarter waits longer, and drops "four months" and "60 to 90 days"; the source names the rules. The NT 10-K point is in Known limits. Not taken here: comparing with Latin American filing calendars (front-end idea, for the app's Spanish text).
- **Explainer.** Its three "blockers" were gaps in the doc, now answered: where `days_q3` comes from (Step 2), how Step 3 reads notes without storing (Step 3), and the new wording (Step 2). Idea 4 (a non-December year end) does not apply: the line keys on the fiscal period, not the month (analyst's check above).
- **Product lead.** OK. Taken: keep `warren_rule` set, and say how the app tells the two lines apart (Product impact).

## Results (nov.12.2026)

- Real data, snapshot of nov.10.2026: of the 13 runs with a stored stale note, rebuilt in memory, 12 no longer warn on this branch and `XOM_2026-10-30_1` still does (213 days after a Q1, line 135); on `main` all 13 warn. Four of the 13 (CAT, KO, XOM 2020-02-15 and JNJ 2024-02-15) rebuild with different rows on both `main` and this branch: they are among the 82 runs v0.9.41 (#264) already rebuilds differently, unchanged by this item. `reproduce --all`: 903 of 903 runs reproduce to the cent.
- Mutation: putting the third quarter back on the 135-day line fails 3 of the new tests.

## PR review (nov.12.2026)

Gatekeeper: GO, no blockers. 2,164 passed, 10 skipped; ruff clean; `reproduce --all` 903 of 903; CI green. Ideas filed as #349: the lesson's 40, 60, 92, 98 and 3 filled from the constants, a test for the underived-Q4 edge, and AAPL's 14-week Q1.

## Product impact

Brief: the run warnings the app shows beside a run (the "Datos" group, v0.9.60) and their lessons. No code, param name or English note text is added, renamed or removed. What changes: (1) a run whose newest quarter is a third quarter warns only after 161 days, so a February run no longer tells a student that the data may be stale when the annual report simply isn't due; (2) `threshold_days` in the note's params can now be 161 as well as 135; (3) the `fundamentals_stale` lesson gains a param, `days_q3` (161), and its sentence names both lines; its `warren_rule` stays set. The note carries no fiscal period: the app tells the two cases apart by `threshold_days` (135 for the 10-Q line, equal to the lesson's `days_q3` for the 10-K line), and should read it from the note, not assume 135. The front-end team will update the brief's "135 días" line and add `days_q3` to #344.
