# Backlog #594: an all-failed grid batch is still a grid batch; the hand-picked horizon is pinned

Issue: https://github.com/sonderbot-ar/warren/issues/594 (from the #593 gatekeeper) · Branch `backlog-594-grid-followups` · Version v0.10.48 when merged.

Status: Done (v0.10.48, nov.25.2026; PR #596, merge `586f17e`, after CI green and a gatekeeper GO).

## Problem

1. **A grid batch where every case failed is not read as a grid batch.** `backtest_report.render` decided `is_grid` from `case_info`, which holds only the cases with result rows. With no rows it was `False`, so the report had no grid sections and its Limitations line used the hand-picked wording ("events were chosen in hindsight…") for a batch of rule-dated cases. Pre-existing.
2. **The hand-picked guard is not pinned on the horizon.** `test_storing_a_grid_case_never_overwrites_a_hand_picked_one` stored a grid copy with the same horizon as the hand-picked case and checked only `event_type`, so removing the `WHERE eval_cases.event_type = 'grid'` guard that #591 added to the upsert still passed.

## Plan

**Step 0. This doc.**

**Step 1. Both, with tests.**
- New `backtest_report.batch_event_types(conn, batch_id)`: the event types of every case with a result row or a failure in the batch. `render` reads the batch as grid when that set is exactly `{"grid"}`. `case_info` is unchanged (it feeds the per-case and group tables, which list scored cases only).
- `tests/evaluation/test_backtest_batch.py::test_a_grid_batch_whose_every_case_failed_is_still_read_as_a_grid_batch` (one grid case that fails: the grid section says 1 case, 0 scored, 1 failed, and the Limitations line counts it) fails on `main`; `test_an_all_failed_event_batch_gets_no_grid_sections` keeps the other side.
- `tests/evaluation/test_grid.py::test_storing_a_grid_case_never_overwrites_a_hand_picked_one`: the grid copy now has horizon 2 against the hand-picked 4, and the test asserts both columns. Checked by removing the guard: the test fails.

Exit: full suite, `ruff check`, `ruff format --check` green. No forecast, error, score or reproduce result changes; only the report of a batch with no result rows can differ, and a batch mixing scored grid cases with a failed non-grid case (none is built today) is no longer read as grid.

## Alternatives considered

- **Read event types from the batch's notes.** The notes do not store the case list's types; joining `eval_failures` to `eval_cases` uses what is already stored.
- **Widen `case_info` to failed cases.** Rejected in #591 for the same reason: the per-case and group tables would list cases with no rows.

## Files to change

`domains/evaluation/backtest_report.py`, `tests/evaluation/test_backtest_batch.py`, `tests/evaluation/test_grid.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. No output a student sees; no field, code or name changes. Brief questions served: none changed.

## Review notes

Explainer, analyst and professor not run: a report switch and a test, with no method or number change (as for #591).

Gatekeeper GO on PR #596: ruff clean, 2942 passed, 10 skipped; the new grid test fails with main's `backtest_report.py`; the hand-picked test fails when the `WHERE eval_cases.event_type = 'grid'` guard is removed; failed cases always have an `eval_cases` row (`store_cases` runs before `record_failure` in `harness.py`). Non-blocking notes taken here: the mixed-batch case is now named in the exit line above. Not filed: a grid case sharing an id with a hand-picked one would keep the hand-picked type and take the batch's grid sections away, as before this change; checked, no grid case id in `grid_cases.csv` (176) matches one in `cases.csv` (26), and `grid.shared_with_hand_picked` lists any that would.
