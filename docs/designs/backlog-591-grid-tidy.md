# Backlog #591: a stored grid case follows the rule's horizon; the grid report counts every case

Issue: https://github.com/sonderbot-ar/warren/issues/591 (from the #589 gatekeeper) · Branch `backlog-591-grid-tidy` · Version v0.10.47 when merged.

Status: Done (v0.10.47, nov.25.2026; PR #593, merge `aa15ee2`, after CI green and a gatekeeper GO).

## Problem

1. **Stored grid horizons keep their first value.** `store_cases` (`domains/evaluation/cases.py`) inserts grid rows with `ON CONFLICT DO NOTHING`, so that a grid case never overwrites a hand-picked case with the same id. The side effect: when the grid rule changes a grid case (v0.10.46 lengthened XOM_2025-05-15 from 3 to 4 quarters and XOM_2025-11-15 from 1 to 4), `eval_cases.horizon_quarters` keeps the old value. Nothing reads that column today (`report.py`, `track_record.py` and `ranges.py` read ticker, date, type and scope only), but a later reader would get the wrong horizon.
2. **The backtest report's Limitations line counts 175 of 176 grid cases.** `backtest_report.render` passes `len(info)` to `_glossary`, and `case_info` holds only the cases with result rows, so a failed case drops out. The grid section above it counts scored, not-yet-scorable and failed cases (`grid_report.counts`), so the two lines of one report disagree (`eval_2026-11-25_1`: 176 against 175).

## Plan

**Step 0. This doc.**

**Step 1. Both fixes, with tests.**
- `store_cases`: a grid row's conflict clause becomes `DO UPDATE SET … WHERE eval_cases.event_type = 'grid'`. It updates every column the rule sets except `event_type` (always `grid` on both sides), and only when the stored row is itself a grid row, so a hand-picked case is still never touched. Docstrings in `cases.py` and `grid.py` say so.
- `render`: the Limitations count is the set of case ids in the batch's result rows and failures, the same set `grid_sections` counts.
- Tests: `tests/evaluation/test_grid.py::test_storing_a_grid_case_again_updates_its_horizon` (store a grid case at 3 quarters, store it again at 4, the row says 4); the existing `test_storing_a_grid_case_never_overwrites_a_hand_picked_one` stays and still passes. `tests/evaluation/test_backtest_batch.py::test_the_grid_limitations_line_counts_failed_cases_too` (a grid batch with one scored and one failed case says 2 in both lines). Both new tests fail on `main`.

Exit: full suite, `ruff check`, `ruff format --check` green. No forecast, error, score or reproduce result changes; only the report's count line and the stored horizon column can differ.

## Alternatives considered

- **Document that the table holds a case's first horizon** (the issue's second option). Cheaper, but leaves a column that is wrong for two cases today and for any later rule change; the fix is one SQL clause.
- **Let `case_info` include failed cases.** It would also fix the count, but `case_info` feeds the per-case table and the groups section, which would then list failed cases with no rows; a bigger change than the issue needs.

## Real data

The stored rows in the snapshot are corrected the next time the grid is stored (any grid batch, `python -m domains.evaluation backtest` on the grid, calls `store_cases`). Not run now: no reader of the column exists, so restoring the 1 GB snapshot only to rewrite two values is not worth it; the next grid batch does it. The report for `eval_2026-11-25_1` will say 176 in both places when it is next rendered.

## Files to change

`domains/evaluation/cases.py`, `domains/evaluation/backtest_report.py`, `domains/evaluation/grid.py` (docstring), `tests/evaluation/test_grid.py`, `tests/evaluation/test_backtest_batch.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. No output a student sees, no field, code or name is added, renamed or removed. The backtest report (an owner-facing file, not an app output) counts its grid cases the same way in both places. Brief questions served: none changed.

## Review notes

Explainer, analyst and professor not run: a storage clause and a count line, with no method or number change (as for #519, #522, #575).

Gatekeeper GO on PR #593: ruff clean, 2940 passed, 10 skipped; both new tests fail with main's `cases.py` and `backtest_report.py`; an upsert whose WHERE is false changes nothing, so a hand-picked row is never touched and `event_type` is not in the SET list; no reader of `eval_cases` uses `horizon_quarters`, and the reproduce paths rebuild cases from the CSV. Non-blocking notes filed as #594: an all-failed grid batch is not read as a grid batch (`is_grid` comes from rows only, pre-existing), and the hand-picked test could pin the horizon too. Not taken: moving two in-function imports in the new report test (style only).
