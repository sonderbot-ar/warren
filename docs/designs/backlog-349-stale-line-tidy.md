# Backlog #349: the stale lesson's numbers come from the constants, and the underived fourth quarter is pinned

Issue: https://github.com/sonderbot-ar/warren/issues/349 · Branch `backlog-349-stale-line-tidy` · Version v0.9.62, merged nov.12.2026 (PR #351, merge `f8b4926`)

## Problem

The review of PR #348 (v0.9.61, backlog #342) left three follow-ups. Everything works today; these are about keeping it that way.

1. **Numbers typed by hand.** The `fundamentals_stale` lesson (`domains/analysis/text.py`) says "60 days … not 40" in its `why`, and "92 days, or 98 …, plus the deadline plus 3 days" in its `warren_rule`. Those five numbers are `math_engine.DEADLINE_10K_DAYS`, `DEADLINE_10Q_DAYS`, `QUARTER_DAYS`, `LONG_QUARTER_DAYS` and `DEADLINE_SLACK_DAYS`, but they are written as text. The lesson test (`tests/analysis/test_warning_lessons.py`, `THRESHOLDS`) checks only `days` and `days_q3`, so changing a deadline would leave the lesson teaching the old one with every test green.
2. **The underived fourth quarter is only written down.** If a 10-K is ingested but its fourth quarter can't be derived (the year's figure is missing, so Q4 = year − Q1 − Q2 − Q3 has no input), the newest quarter stays Q3 and the 161-day line applies (`docs/designs/backlog-342-stale-after-q3.md`, Known limits 2). No test pins that.
3. **AAPL's 14-week first quarter.** AAPL's 53rd week falls in Q1, so in a 53-week year its first 10-Q can be due 138 days after its last quarter, past the 135-day line. AAPL filed at 132 days; no stored run is affected.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. The lesson's numbers from the constants.** In `text.py`, `fundamentals_stale`:
  - `why`: the typed "60" and "40" become placeholders `{deadline_10k}` and `{deadline_10q}`, and `params` gains `deadline_10k` = `DEADLINE_10K_DAYS` (60) and `deadline_10q` = `DEADLINE_10Q_DAYS` (40). The English a student reads is unchanged word for word.
  - `warren_rule` is built with an f-string from the five parts and the two lines, and now pairs each line with its own parts (analyst): "both lines are working rules (math_engine.STALE_AFTER and STALE_AFTER_Q3): 135 days is a 92-day quarter plus the 40-day 10-Q deadline plus 3 days; 161 days is a 98-day fourth quarter (14 weeks, in a 53-week year) plus the 60-day 10-K deadline plus 3 days". The 98-day quarter belongs only to the 161-day line (explainer). `warren_rule` stays an English pointer for the owner; the app shows "Criterio propio de Warren", not this text (product lead; `docs/product/brief.md`, "Each estimate note teaches").
  - Tests (`tests/analysis/test_warning_lessons.py`): `THRESHOLDS["fundamentals_stale"]` gains the two deadlines, so the existing test checks they appear in the lesson and its rule. A new test reads the rule's two "N days is a Q-day quarter plus the D-day form deadline plus S days" clauses from the text and checks each against the constants, in order, and that each adds up. So the test reads the English, not the constants twice (explainer).
  - Exit: tests pass. Checked by hand: typing "60" back into the rule and changing `DEADLINE_10K_DAYS` to 61 fails 2 tests; changing the constant alone fails none (the text follows).
- **Step 2. Pin the underived fourth quarter.** In `tests/analysis/test_build_warning_codes.py`: Test Corp with every filing before 2020-03-01 (so the FY2019 10-K, filed 2020-02-15, is in) but without the 10-K's `Revenues` row for 2019-01-01 to 2019-12-31. Test Corp's 10-K files only full years, so Q4 2019 revenue (year − Q1 − Q2 − Q3, `domains/fundamentals/facts.py`) has no year to start from. The test checks the case is the one meant (10-K rows at 2019-12-31 are in `financial_facts`; the run rolls forward from `FY2019Q3`, read from the `roll_years` row's source), then that the 161-day line applies: no note at 161 days (2020-03-09), a note with `threshold_days` 161 at 162 days (2020-03-10). What it adds to the existing Q3 test: there the 10-K is not filed yet; here it is, and the line still keys on the newest quarter, not on which forms are in.
  - Exit: test passes; putting Q3 back on the 135-day line fails both cases (checked).
- **Step 3. AAPL's first quarter: written down, not built.** No code and no test. Known limits below records it, beside #342's Known limits 1 (that doc is not edited), and the fix is the per-company deadline in Phase 2 (#342's Alternatives). Exit: this section and Known limits.

## Alternatives considered

- **A test that the lesson's text contains the constants, leaving the text typed by hand** (the issue's second option). Rejected: it catches the drift but still needs a hand edit; filling from params makes the app's Spanish text follow the same numbers, which is the rule every other lesson follows (`Lesson` docstring).
- **Move the AAPL case into the line now: 141 days after a fourth quarter** (98 + 40 + 3). Rejected: it would hide a missing first-quarter 10-Q for six extra days for the seven companies whose first quarter is never 14 weeks, to fix a case no stored run hits. The per-company calendar is the right fix and is Phase 2.

## Known limits

AAPL's 14-week first quarter (item 3) stays as #342 left it: in a 53-week year a run made between 136 and 138 days after AAPL's fourth quarter, with the 10-Q not yet filed, would warn although the filing isn't late. AAPL has filed at 132 days or sooner every year since 2019 (analyst, #342).

Once a later 10-Q arrives while the fourth quarter is still missing, the run stops with an error from the revenue seed (`math_engine._revenue_seed`, a gap in the seed quarters) instead of warning (analyst). That is the right outcome, and unchanged here.

**Point in time.** Nothing new is read. **LLMs.** None. **Decision 11.** No source, company or currency change. **Stored runs.** Lessons are not stored; nothing changes in `run_notes` or any run.

## Files to change

`domains/analysis/text.py`, `tests/analysis/test_warning_lessons.py`, `tests/analysis/test_build_warning_codes.py`, this doc; at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Brief: the lesson the app shows beside a `fundamentals_stale` warning (the "Datos" group, v0.9.60). Added: two params on that lesson, `deadline_10k` (60) and `deadline_10q` (40), so the app's Spanish lesson can fill the deadlines from Warren's numbers like it does `days` and `days_q3`. Changed: the lesson's `warren_rule` English names the two deadlines. Nothing renamed or removed; the warning itself (code, params, text) is unchanged. `warren_rule` is not shown to students (the app shows "Criterio propio de Warren"). For the front-end team: add `deadline_10k` and `deadline_10q` to #344 next to `days_q3`, so the Spanish lesson names both deadlines from the params when the brief's "135 días" line is updated (due since v0.9.61).

## Design review (nov.12.2026)

Explainer, analyst and professor in parallel, and the product lead on *Product impact*. Analyst GO, professor GO, product lead OK.

- **Analyst.** Checked on code that the newest quarter is chosen from revenue alone (`math_engine._last_actual_quarter`) and that Q4 exists only as a derivation that needs the year (`facts.py`), so the fixture is a faithful stand-in; AAPL's next 53-week year is about FY2028, past Phase 1. Taken: each line shown with its own parts (idea 1); the seed error after a later 10-Q is in Known limits (idea 4). Filed as backlog: a note param saying the annual report is in but the fourth quarter could not be derived (idea 2); the NT 10-K/10-Q late-filing notice in the lesson (idea 3, also the professor's).
- **Professor.** Fetched Forms 10-Q and 10-K: 40 and 60 days for large accelerated filers; 135 = 92 + 40 + 3 and 161 = 98 + 60 + 3. Taken: `warren_rule` stays an English pointer (Step 1). Not taken here: splitting the `why` sentence for Spanish (the app writes its own sentence from the params).
- **Explainer.** Five "blockers", all gaps in the doc, now answered in Steps 1–3: the literals are replaced; the 98 days belongs to the 161-day line only; the test reads the English; students never see `warren_rule`; Step 3 has an exit and edits no other doc. Ideas 6 and 7 answered in Step 2.
- **Product lead.** OK. Taken: the front-end team adds `deadline_10k` and `deadline_10q` to #344 next to `days_q3` (Product impact).

## PR review (nov.12.2026)

Gatekeeper: GO, no blockers. `tests/analysis` 643 passed; ruff clean; CI green; the student's English rendered identical on `main` and the branch; both mutations fail the new tests. Idea, filed with #352: assert the rule's regex finds two clauses before comparing, so a wording edit fails with a clear message.
