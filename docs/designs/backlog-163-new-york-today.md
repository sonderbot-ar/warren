# Backlog #163: the New York day, not the machine's date, for "today" defaults

Issue: https://github.com/sonderbot-ar/warren/issues/163 · Branch `backlog-163-new-york-today` · Version v0.9.24 when merged.

## Problem

From the design review of #128 (PR #161, explainer). Nine places take `date.today()` (and the scan found a tenth, below), the machine's date:

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

**Step 1. Two kernel helpers and the call sites.** `shared_kernel/calendar.py` gains `case_today(now, tz=CASE_TZ)`, the date in New York at `now` (for labels and upper bounds, never a data cut-off), beside `last_ended_day(now, tz=CASE_TZ)`, which is now `case_today(now) - 1 day` (for data cut-offs); both raise `ValueError` on a naive `now`. Each call site reads the clock once, as a local `now = datetime.now(UTC)` (no new parameter):

- data cut-offs default to `last_ended_day(now)`, as runs already do since v0.9.7: the fallback check, the quality report, `evaluate_case`'s `actuals_as_of`, `run_backtest`'s `actuals_as_of`, `build_origins`'s `actuals_as_of` and last origin, and the `actuals_as_of` that `ranges test` passes to `run_build` (its first positional argument, `domains/evaluation/__main__.py`);
- labels use `case_today(now)`: the `eval_<date>_<n>` id (`new_batch`) and the `ranges_<date>_<n>` id (`run_build`);
- upper bounds use `case_today(now)`: `build_inputs` (so a run may still be dated the current New York day; see the deferred item below), and through it the runs that `run_backtest` and `build_origins` make when no `today` is given (they now pass `None` down and `build_inputs` takes the default);
- `run_backtest` splits its one `today` into two values: `actuals_as_of = actuals_as_of or today or last_ended_day(now)` and the label and bound `today or case_today(now)`. An explicit `today` therefore still serves as the actuals default, exactly as before, so every stored batch reproduces; only the default path splits. `build_origins` does the same (`last = today or last_ended_day(now)` for its cut-off and last origin; `today` passed on unchanged);
- found by the scan: the pipeline's `Deps.today()` (`domains/orchestration/nodes.py`) was the UTC date of its injected clock; it is now `case_today(self.now())`. It decides only whether a pipeline's review is manual (a date within a week) or auto.

A label is not a cut-off: a batch labelled `eval_2026-11-06_1` made in the evening of nov.06 in New York holds actuals filed up to the end of nov.05. Old ids keep their UTC dates; ids made after this change on the same New York evening may read one day earlier than they would have. The counter (`LIKE prefix%`) cannot collide either way.

Tests (`tests/evaluation/test_new_york_today.py`, the clock frozen at 2026-07-02 02:00 UTC, which is July 1 in New York and June 30 as the last ended day, so the three possible answers differ): a default backtest is `eval_2026-07-01_1` with `actuals_as_of` 2026-06-30; an explicit `today` still sets both; `evaluate_case` reads actuals known by June 30; `build_inputs` refuses the machine's July 2 and names July 1 as the bound; the quality report, the fallback check, `build_origins` and `ranges test` default to June 30; a range build is `ranges_2026-07-01_1`; `Deps.today()` is July 1. In `tests/shared_kernel/test_calendar.py`: `case_today` at New York midnight in summer and winter and refusing a naive time; an AST scan over `main.py`, `domains/`, `shared_kernel/` and `webapp/` that fails on `today()`, `utcnow()`, `utcfromtimestamp()`, or a `now()` with no argument or `None`, on the `date` and `datetime` types under any import alias (injected clocks such as `deps.now()` are not the machine's); a test that the scan catches each form; and a check that it sees every fixed module and the app. Checked by mutation: with `run_backtest`'s cut-off on `case_today`, the backtest test fails. Exit: ruff and the full suite green; no stored number changes (every stored batch, origin and range was made with explicit dates, and `build_origins` already stops at `LAST_ORIGIN`, 2026-10-01, before any last ended day from now on).

**Deferred (backlog issue, labelled `front-end`).** A run dated the current New York day is not yet closed: `known_by(case_today)` is still ahead, so two runs with the same as-of date made at 14:00 and at 23:00 can see different filings or prices. The brief already tells students the engine refuses a day still in progress (`docs/product/brief.md`, the corte), and the pipeline does (`nodes.check_closed`), but `build_inputs` and `dcf --as-of <today>` do not. Whether to tighten the bound is the front-end's product question (Decision 13), so it is filed as issue #223, not decided here.

## Alternatives considered

- *`last_ended_day` everywhere, labels and bounds too.* Rejected: an id dated yesterday reads wrong, and the tighter bound changes what `dcf --as-of` accepts (a product decision, out of scope).
- *Set the process time zone (`TZ=America/New_York`).* Rejected: it hides the rule in the environment, and the engine's rule is the kernel's (Decision 11, guardrail 1).
- *Leave the labels on the machine's date.* Rejected: two machines would label the same New York day differently.

## Product impact

Serves no brief question directly; it keeps the defaults behind every screen on one calendar. No output, name or field is added, renamed or removed. New public helper `shared_kernel.calendar.case_today(now)`, for ids and labels only: anything a student reads as a date (the *fecha de corte*, "hoy") stays on `last_ended_day`, as `webapp/` already does, so the header's promise holds. New rule for both teams: the clock scan covers `webapp/` too, so a front-end change that calls `date.today()`, `datetime.now()` with no time zone, or `utcnow()` fails CI. The brief's line that the engine refuses a day in progress is true for the pipeline but not yet for `dcf --as-of <today>`; that is the deferred issue above, for the front-end to decide.

## Design review (nov.06.2026)

All four GO, no blockers. Accepted: the explainer's gaps (the helpers' signatures and error; `now` a local, not a parameter; how `run_backtest`'s one `today` splits; what the runs' bounds become; `build_origin`'s `today`), now in Step 1. The analyst's and professor's notes: say that an explicit `today` still sets the actuals; file the same-day run as an issue (done, labelled `front-end` at the product lead's ask); widen the scan to `today()`, `utcnow()` and `now(None)` under aliases; a whole-backtest test at a time when the three days differ; say a label is not a cut-off and that old ids keep their UTC dates; name the origin cap's no-op in the exit criterion. The product lead's: `case_today` for labels only, never a date a student reads; the scan's new rule on `webapp/`. Rejected with a reason: the explainer's and professor's reading that `ranges test` passes the machine's date as a label; `run_build`'s first positional argument is `actuals_as_of` (`domains/evaluation/ranges.py`, `run_build`), as the analyst confirmed, so it is a cut-off and gets `last_ended_day`.

## Files to change

`shared_kernel/calendar.py`, `domains/analysis/__main__.py`, `domains/analysis/math_engine.py`, `domains/fundamentals/quality.py`, `domains/evaluation/harness.py`, `domains/evaluation/backtest_batch.py`, `domains/evaluation/ranges.py`, `domains/evaluation/__main__.py`, `domains/orchestration/nodes.py`, `tests/shared_kernel/test_calendar.py`, a new `tests/evaluation/test_new_york_today.py`; at merge `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (roadmap only).
