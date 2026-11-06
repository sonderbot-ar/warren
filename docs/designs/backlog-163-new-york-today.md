# Backlog #163: the New York day, not the machine's date, for "today" defaults

Issue: https://github.com/sonderbot-ar/warren/issues/163 · Branch `backlog-163-new-york-today` · Version v0.9.24 when merged.

## Problem

From the design review of #128 (PR #161, explainer). Nine places take `date.today()`, the machine's date:

| Where | What the date does |
|---|---|
| `domains/analysis/__main__.py`, `cmd_fallbacks` | as-of of the fallback check (a data cut-off) |
| `domains/fundamentals/quality.py`, `build_report` | as-of of the quality report (a data cut-off) |
| `domains/evaluation/harness.py`, `evaluate_case` | `actuals_as_of` default (a data cut-off) |
| `domains/evaluation/backtest_batch.py`, `run_backtest` | `actuals_as_of` default, the batch id's date, the runs' upper bound |
| `domains/evaluation/ranges.py`, `build_origins` | last origin date, `actuals_as_of` default, the runs' upper bound |
| `domains/evaluation/__main__.py`, `cmd_ranges_test` | `actuals_as_of` of `ranges test` (a data cut-off) |
| `domains/evaluation/harness.py`, `new_batch` | the `eval_<date>_<n>` id (a label) |
| `domains/evaluation/ranges.py`, `run_build` | the `ranges_<date>_<n>` id (a label) |
| `domains/analysis/math_engine.py`, `build_inputs` | the upper bound on a run's as-of date |

v0.9.7 (#128) made `shared_kernel.calendar.last_ended_day(now)`, the last day that has ended in New York, the default as-of for runs. On a machine east of New York after its midnight (a cloud machine on UTC from 20:00 New York time in summer), `date.today()` is a day that has not started in New York: a data cut-off counts filings and prices from a day not yet over, and the run bound admits a date that is still in the future in the case calendar.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. Two kernel helpers and the nine call sites.** `shared_kernel/calendar.py` gains `case_today(now)`, the date in New York at `now` (a calendar date, for labels and upper bounds), beside `last_ended_day(now)` (for data cut-offs); both refuse a naive `now`. Each call site above takes `now = datetime.now(UTC)`:

- data cut-offs (fallbacks, quality report, `actuals_as_of` in the harness, the batch, the origins and `ranges test`) default to `last_ended_day(now)`, as runs already do since v0.9.7;
- labels (the batch and range-build ids) use `case_today(now)`;
- the run bound in `build_inputs` uses `case_today(now)`, so it keeps today's meaning (a run may be dated today) on the New York calendar. Tightening it to the last ended day is a separate product question (it would refuse `dcf --as-of <today>`), not part of this item;
- `build_origins` stops its origin dates at `last_ended_day(now)`.

An explicit `today`, `actuals_as_of` or `--as-of` argument behaves exactly as before, so every stored batch, origin and range reproduces unchanged.

Tests: `case_today` at the New York midnight in summer and winter and refusing a naive time; each data default equals `last_ended_day` and each label `case_today` at 02:00 UTC (when the UTC date is one day ahead of New York's), patching `datetime.now` in the module under test; an AST scan over `main.py`, `domains/`, `shared_kernel/` and `webapp/` that fails on any `date.today()` or argument-less `datetime.now()`, and checks it sees at least the nine fixed modules (so an empty scan can't pass). Exit: ruff and the full suite green; no stored number changes.

## Alternatives considered

- *`last_ended_day` everywhere, labels and bounds too.* Rejected: an id dated yesterday reads wrong, and the tighter bound changes what `dcf --as-of` accepts (a product decision, out of scope).
- *Set the process time zone (`TZ=America/New_York`).* Rejected: it hides the rule in the environment, and the engine's rule is the kernel's (Decision 11, guardrail 1).
- *Leave the labels on the machine's date.* Rejected: two machines would label the same New York day differently.

## Product impact

Serves no brief question directly; it keeps the defaults behind every screen on one calendar. No output, name or field is added, renamed or removed. New public helper `shared_kernel.calendar.case_today(now)`. The app already uses `last_ended_day` (`webapp/`), so nothing changes there; a screen that labels "today" should use `case_today`.

## Files to change

`shared_kernel/calendar.py`, `domains/analysis/__main__.py`, `domains/analysis/math_engine.py`, `domains/fundamentals/quality.py`, `domains/evaluation/harness.py`, `domains/evaluation/backtest_batch.py`, `domains/evaluation/ranges.py`, `domains/evaluation/__main__.py`, `tests/shared_kernel/test_calendar.py`, a new `tests/shared_kernel/test_new_york_today.py`; at merge `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (roadmap only).
