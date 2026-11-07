# Backlog #241: pin the equal-rate edge of the floor, tighten one refusal test, build the stage-2 test rows with the code's own stage 1

Issue: https://github.com/sonderbot-ar/warren/issues/241 · Branch `backlog-241-floor-tests`.

## Problem

The gatekeeper's review of PR #240 (v0.9.29) found three test gaps in the leverage what-if. All of it is correct today.

1. **Equal rates are not pinned.** `_would_floor` (`domains/analysis/whatif.py`) floors the cost of debt when it is strictly below the risk-free rate. Changing `<` to `<=` passes every test, and would add a no-op `floored_at_risk_free` row (before and after equal) when the two rates are equal.
2. **One refusal test is thin.** `test_a_run_with_debt_and_a_zero_book_rate_unchanged_debt_is_refused` checks only the code, not the text, the params or that nothing was stored.
3. **The `_stage2` test helper copies stage 1.** It rebuilds the rows `_changed_rows` makes and labels every row "set" (a delta should be "add"), so it could drift from the code.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. Stage 1 as its own function.** Move stage 1 of `_changed_rows` (each change's shape, its before and after, and its `how`) into `_shape_rows(rows, changes, parent_outputs)`, returning the parent's rows by key, the moved rows and the forecast periods. `_changed_rows` calls it and goes on with stages 2 and 3 unchanged. The tests' `_stage2` helper calls `_shape_rows` instead of copying it.
  Tests: a new test that the helper's rows carry `add` for a delta and `set` for a value, with the parent's befores; the five-case `_would_floor` test and the debt-to-zero test now run on the code's own rows.
  Exit: every existing test passes unchanged in what it asserts.
- **Step 2. The two pins.** A test where the student sets the risk-free rate equal to the run's cost of debt beside more debt: `_would_floor` is False, the child stores no cost-of-debt row, no floored note, and it reproduces. Checked by hand: with `<=` the test fails. The thin refusal test now also checks `debt_before`, the "free" sentence (not "had no debt") and that no run was stored, like the zero-rate test above it.
  Exit: tests pass.

**Exit criterion:** all tests pass, ruff clean, no request changes outcome, no stored number or text changes. No real-data step: nothing reads data or changes a computation.

**Point in time.** Nothing new is read. **LLMs.** None.

## Alternatives considered

- **Keep the helper and fix its labels.** Rejected: it would still be a copy that can drift, which is the issue's point.
- **Test stage 2 only through `revalue`.** Rejected: `_would_floor` is the one place the condition lives (v0.9.29), and a direct test says which branch failed; the parametrized test already checks both.
- **Floor at equal rates too.** Rejected: the row would change nothing and add a note saying the rate was floored when it wasn't moved.

## Files to change

`domains/analysis/whatif.py`, `tests/analysis/test_whatif.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. No code, param, output or text added, renamed or removed; no request changes outcome. Brief questions Q7 and Q8 (what-if) unchanged.

## Design review (nov.07.2026)

Explainer, analyst and professor in one fresh-context panel. GO, no blockers. Explainer: clear; its two guesses (reproduces means `reproduce(...).ok`; the equal-rate test sets `risk_free` to the exact stored float) are both what the test does. Analyst: the move is exact (stages 2 and 3 unchanged), 123 what-if tests pass, and three mutations in a throwaway worktree were each caught: `<=` in `_would_floor` (only the new equal-rate test fails), the "free" sentence removed, and `add` relabelled `set` in `_shape_rows`. Professor: defensible (a rate already at the floor is left alone) and no scope creep.

- **Not taken:** a NamedTuple for `_shape_rows`' three values (one caller in the code, one in the tests; not worth a new type); moving the backlog reference out of the docstring (the module cites its backlog items in docstrings throughout); a held-rate assertion in the equal-rate test (the missing `cost_of_debt` row already shows it was held).
