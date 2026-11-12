# Backlog #349: the stale lesson's numbers come from the constants, and the underived fourth quarter is pinned

Issue: https://github.com/sonderbot-ar/warren/issues/349 · Branch `backlog-349-stale-line-tidy` · Status: In progress (nov.12.2026)

## Problem

The review of PR #348 (v0.9.61, backlog #342) left three follow-ups. Everything works today; these are about keeping it that way.

1. **Numbers typed by hand.** The `fundamentals_stale` lesson (`domains/analysis/text.py`) says "60 days … not 40" in its `why`, and "92 days, or 98 …, plus the deadline plus 3 days" in its `warren_rule`. Those five numbers are `math_engine.DEADLINE_10K_DAYS`, `DEADLINE_10Q_DAYS`, `QUARTER_DAYS`, `LONG_QUARTER_DAYS` and `DEADLINE_SLACK_DAYS`, but they are written as text. The lesson test (`tests/analysis/test_warning_lessons.py`, `THRESHOLDS`) checks only `days` and `days_q3`, so changing a deadline would leave the lesson teaching the old one with every test green.
2. **The underived fourth quarter is only written down.** If a 10-K is ingested but its fourth quarter can't be derived (the year's figure is missing, so Q4 = year − Q1 − Q2 − Q3 has no input), the newest quarter stays Q3 and the 161-day line applies (`docs/designs/backlog-342-stale-after-q3.md`, Known limits 2). No test pins that.
3. **AAPL's 14-week first quarter.** AAPL's 53rd week falls in Q1, so in a 53-week year its first 10-Q can be due 138 days after its last quarter, past the 135-day line. AAPL filed at 132 days; no stored run is affected.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. The lesson's numbers from the constants.** In `text.py`, `fundamentals_stale`:
  - `why` gets two more placeholders, `{deadline_10k}` and `{deadline_10q}`, and `params` gains `deadline_10k` = `DEADLINE_10K_DAYS` (60) and `deadline_10q` = `DEADLINE_10Q_DAYS` (40). The English is unchanged word for word.
  - `warren_rule` is built with an f-string from `QUARTER_DAYS`, `LONG_QUARTER_DAYS`, `DEADLINE_10Q_DAYS`, `DEADLINE_10K_DAYS`, `DEADLINE_SLACK_DAYS` and the two lines. It now names the two deadlines: "the 135- and 161-day lines are working rules: a quarter (92 days, or 98 for a 14-week fourth quarter) plus the filing deadline (40 days for a 10-Q, 60 for a 10-K) plus 3 days, math_engine.STALE_AFTER and STALE_AFTER_Q3".
  - Tests (`tests/analysis/test_warning_lessons.py`): `THRESHOLDS["fundamentals_stale"]` gains the two deadlines, so the existing test checks they appear in the lesson and in its rule. A new test checks that every one of the five parts and both lines appear in `warren_rule`, and that each line equals its parts' sum (so the rule's arithmetic is the code's).
  - Exit: tests pass; the shown text is unchanged except the rule's added "(40 days for a 10-Q, 60 for a 10-K)"; typing a number back by hand with a different constant fails a test (checked by changing a constant in a scratch copy).
- **Step 2. Pin the underived fourth quarter.** In `tests/analysis/test_build_warning_codes.py`: Test Corp with every filing before 2020-03-01 (so the FY2019 10-K is in) but without the 10-K's full-year 2019 revenue. The test first checks the case is the one meant (the 10-K's balance sheet at 2019-12-31 is in the database, and there is no Q4 2019 revenue), then that the newest quarter is Q3 2019 and the 161-day line applies: no note at 161 days (2020-03-09), a note with `threshold_days` 161 at 162 days (2020-03-10).
  - Exit: test passes; changing the line back to 135 for Q3 fails it.
- **Step 3. AAPL's first quarter: written down, not built.** No code. The Known limits below and the issue say where it goes: the per-company deadline in Phase 2 (#342's Alternatives), which reads each company's own calendar. Closing #349 leaves this item recorded in the design doc of #342 and here.

## Alternatives considered

- **A test that the lesson's text contains the constants, leaving the text typed by hand** (the issue's second option). Rejected: it catches the drift but still needs a hand edit; filling from params makes the app's Spanish text follow the same numbers, which is the rule every other lesson follows (`Lesson` docstring).
- **Move the AAPL case into the line now: 141 days after a fourth quarter** (98 + 40 + 3). Rejected: it would hide a missing first-quarter 10-Q for six extra days for the seven companies whose first quarter is never 14 weeks, to fix a case no stored run hits. The per-company calendar is the right fix and is Phase 2.

## Known limits

AAPL's 14-week first quarter (item 3) stays as #342 left it: in a 53-week year a run made between 136 and 138 days after AAPL's fourth quarter, with the 10-Q not yet filed, would warn although the filing isn't late. AAPL has filed at 132 days or sooner every year since 2019 (analyst, #342).

**Point in time.** Nothing new is read. **LLMs.** None. **Decision 11.** No source, company or currency change. **Stored runs.** Lessons are not stored; nothing changes in `run_notes` or any run.

## Files to change

`domains/analysis/text.py`, `tests/analysis/test_warning_lessons.py`, `tests/analysis/test_build_warning_codes.py`, this doc; at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Brief: the lesson the app shows beside a `fundamentals_stale` warning (the "Datos" group, v0.9.60). Added: two params on that lesson, `deadline_10k` (60) and `deadline_10q` (40), so the app's Spanish lesson can fill the deadlines from Warren's numbers like it does `days` and `days_q3`. Changed: the lesson's `warren_rule` English names the two deadlines. Nothing renamed or removed; the warning itself (code, params, text) is unchanged.
