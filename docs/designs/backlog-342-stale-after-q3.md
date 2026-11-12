# Backlog #342: no "stale" warning while the annual report is simply not due yet

Issue: https://github.com/sonderbot-ar/warren/issues/342 · Branch `backlog-342-stale-after-q3` · Status: in progress (nov.12.2026).

## Problem

A run warns `fundamentals_stale` when its newest quarter ended more than 135 days before the run's date (`STALE_AFTER`, `domains/analysis/math_engine.py:68`, checked in `_last_actual_quarter`). 135 days fits a quarterly report: a quarter of about 92 days, then 40 days to file the 10-Q (large accelerated filer), then 3 days for a deadline that falls on a weekend or holiday.

After a third quarter the next report is the 10-K, due 60 days after the year ends, so about 152 days after a September 30 quarter end. On the snapshot of nov.10.2026, 12 of the 13 stored `fundamentals_stale` notes are February 15 runs whose last quarter is a fiscal Q3 (CAT, JNJ, KO, XOM in 2020, 2022 and 2024, and KO in 2026, 137 to 142 days). Every one of those companies filed its 10-K on time (for example CAT 2024-02-16, XOM 2024-02-28). The warning is false. The 13th, `XOM_2026-10-30_1` (last quarter 2026-03-31, 213 days), is a real gap: Exxon's history ends when it reorganised (`domains/fundamentals/universe.csv`), and it must keep warning.

The lesson for this warning (`domains/analysis/text.py`, `fundamentals_stale`, v0.9.60) already tells the student that the annual report can come about 150 days after the third quarter. The warning should agree with its own lesson.

## The rule (fixed here)

The line depends on which report comes next, read from the newest quarter's fiscal period:

| Newest quarter | Next report | Line | Built from |
|---|---|---|---|
| Q1, Q2 or Q4 | 10-Q | 135 days (unchanged) | 92-day quarter + 40-day 10-Q deadline + 3 days |
| Q3 | 10-K | **161 days** | 98-day fourth quarter + 60-day 10-K deadline + 3 days |

The fourth quarter is taken at 98 days, not 92, because the 52/53-week filers in the universe (KO, JNJ, AAPL) have a 14-week fourth quarter in a 53-week year, and their fiscal Q3 can end as early as September 26 (KO 2025: September 26 to the 10-K deadline of March 2, 2026 is 157 days, so a 155-day line would still warn falsely). Deadlines are the large accelerated filer ones (SEC Form 10-Q and Form 10-K, General Instruction A); every company in the universe is one, and the 135-day line already assumed it. The 3 days cover a deadline that moves to the next business day (Exchange Act Rule 0-3).

Both lines stay working rules in `math_engine.py`, now built from named parts so their source is in the code: `STALE_AFTER` (10-Q, 135) and `STALE_AFTER_Q3` (10-K, 161).

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. The rule.** `math_engine.py`: `QUARTER_DAYS = 92`, `LONG_QUARTER_DAYS = 98`, `DEADLINE_10Q = 40`, `DEADLINE_10K = 60`, `DEADLINE_SLACK = 3`; `STALE_AFTER = timedelta(QUARTER_DAYS + DEADLINE_10Q + DEADLINE_SLACK)` (135, unchanged) and `STALE_AFTER_Q3 = timedelta(LONG_QUARTER_DAYS + DEADLINE_10K + DEADLINE_SLACK)` (161). `_last_actual_quarter` picks the line from `last.fiscal_period`; the note's code, params (`last_quarter_end`, `days`, `threshold_days`) and English text keep their shape, and `threshold_days` is the line used (135 or 161).
  Tests (`tests/analysis/test_build_warning_codes.py`): the existing 182-day Q4 case is unchanged (`threshold_days` 135); a last quarter that is Q3 at 138 days gives no note (the CAT 2024 case); a Q3 at 162 days warns with `threshold_days` 161; a Q2 at 136 days still warns with 135. Boundary: exactly 161 days after a Q3 does not warn (the check is "more than").
  Exit: tests pass; changing the Q3 branch back to 135 fails a test.
- **Step 2. The lesson.** `text.py`, `fundamentals_stale`: the sentence names both lines, `{days}` (135) for a quarterly report and `{days_q3}` (161) after a third quarter, and the source line names the deadlines instead of "a working rule". `tests/analysis/test_warning_lessons.py` gets the new param.
  Exit: the lesson tests pass and the lesson's numbers come from the constants, not typed twice.
- **Step 3. Real data.** On the restored snapshot (nov.10.2026, 903 stored runs): rebuild the 13 runs with a stored `fundamentals_stale` note on this branch and list which still warn (expected: only `XOM_2026-10-30_1`); `reproduce --all` (numbers do not change: the line only decides a note).
  Exit: 12 of 13 lose the note, XOM 2026-10-30 keeps it, every run reproduces.

**Stored runs.** Notes are stored with each run (`run_notes`) and are not rewritten; `reproduce` compares assumption rows, not notes (`domains/analysis/runs.py`, `rebuild`). So the 12 stored false notes stay on their old runs, and only runs made after the merge follow the new line. Rewriting stored notes would change stored history for a wording-level fix; not done.

**Point in time.** Nothing new is read; the line uses the newest quarter the run already saw as of its date. **LLMs.** None. **Decision 11.** No source, company or currency change. The deadlines are US SEC ones; a later non-US adapter would bring its own (noted in the code).

## Alternatives considered

- **One line of about 155 days for every quarter** (the issue's second option). Rejected: it would hide a missing 10-Q for three extra weeks on the three quarters where 135 days is right.
- **155 days after a Q3** (92-day quarter). Rejected: KO's fiscal Q3 ended September 26, 2025, so its on-time 10-K could arrive 157 days later; a 14-week fourth quarter must fit.
- **Read the filer status and the exact fiscal year end from the filings** (accelerated vs large accelerated, 52/53-week calendar). Rejected for now: all eight companies are large accelerated filers; the per-company deadline is a Phase 2 item for a wider universe, and the named constants make it a one-place change.
- **Rewrite the 12 stored false notes.** Rejected: stored runs keep what they said when made (the same rule as other note changes, e.g. v0.9.15).

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/text.py`, `tests/analysis/test_build_warning_codes.py`, `tests/analysis/test_warning_lessons.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief: the run warnings the app shows beside a run (the "Datos" group, v0.9.60) and their lessons. No code, param name or English note text is added, renamed or removed. What changes: (1) a run whose newest quarter is a third quarter warns only after 161 days, so a February run no longer tells a student that the data may be stale when the annual report simply isn't due; (2) `threshold_days` in the note's params can now be 161 as well as 135; (3) the `fundamentals_stale` lesson gains a param, `days_q3` (161), and its sentence names both lines. The app should read `threshold_days` from the note, not assume 135.
