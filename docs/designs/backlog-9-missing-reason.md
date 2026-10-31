# Backlog #9: store why a DCF output is missing

Issue: https://github.com/sonderbot-ar/warren/issues/9 · Branch `backlog-9-missing-reason` · Version v0.5.2 when merged.

## Problem

Each baseline run stores value per share at the equity risk premium ± 1 standard error (M2.1). When a shifted ERP leaves the DCF without a value, `dcf.run_outputs` catches the `FinancialMathError` and drops the output (`domains/analysis/dcf.py`, the loop at the end of `run_outputs`). Three places then name the cause without knowing it:

- `report._sensitivity` prints "no value (WACC ≤ growth)";
- `report._precision` says "WACC falls to terminal growth or below";
- `runs.run_baseline` writes the note "WACC ≤ terminal growth".

That was right under the Gordon terminal value (M2), which fails exactly when WACC ≤ g. Since M4 the owner's terminal rule is the value-driver formula NOPAT × (1 + g) / WACC (Structure Guide Decision 4, oct.30.2026), which never fails at WACC ≤ g; it fails only when WACC ≤ 0 (`financial_math.value_driver_terminal_value`). Under today's rule the stated cause is wrong. A report that names the wrong cause teaches the wrong lesson, which matters for a teaching tool (Decision 11).

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. Errors carry a reason code.** `FinancialMathError(message, reason="invalid_input")` gains a `reason` attribute; it stays a `ValueError`, so every existing `except` and `pytest.raises` still works. Codes, set where the error is raised:

| Code | Raised by | Plain words in the report |
|---|---|---|
| `growth_not_below_rate` | `gordon_terminal_value` | WACC ≤ terminal growth |
| `rate_not_positive` | `value_driver_terminal_value` | WACC ≤ 0 |
| `rate_not_above_minus_100` | `discount_factors` | WACC ≤ −100% |
| `invalid_input` | every other check | the error's own message |

`REASONS` in `financial_math.py` maps each code to its words. No number changes: the functions compute exactly as before.
Tests: each of the three raises carries its code; any other raise carries `invalid_input`; the existing `match=` tests still pass. Exit: `pytest`, `ruff check`, `ruff format --check` green.

**Step 2. Store the reason with the run (migration `0013_run_output_gaps.sql`).**

```text
run_output_gaps(run_id REFERENCES runs, name, period, reason, detail, PRIMARY KEY (run_id, name, period))
```

- `dcf.outputs_and_gaps(rows)` returns the outputs and, for each output it could not compute, `Gap(reason, detail)` (detail is the error message). `run_outputs(rows)` stays and returns the outputs only, so callers that only need numbers don't change.
- `runs.save_run` writes the gap rows in the same transaction as the outputs; `runs.load_gaps` reads them. A reason code outside `REASONS` is refused on write and on read (`ValueError`), so the column stays typed without a CHECK that a new code would force a table rebuild for.
- `reproduce` also compares each stored gap with today's: a gap whose reason changed is a mismatch. A run stored before 0013 has no gap rows; its missing outputs are still checked as before (stored missing, now missing), only the reason isn't compared.
- `run_baseline`'s note names the stored reason ("No value per share at erp minus 1se: WACC ≤ 0").
- The migration is additive (a new table, no rewrite), so an existing database upgrades in place.
Tests: a Gordon run with ERP − 1 SE at WACC = g stores `growth_not_below_rate`; a value-driver run with WACC ≤ 0 stores `rate_not_positive`; a run with a value stores no gap; reproduce reports a mismatch when a stored reason is edited; a v12 database with a stored run upgrades to v13, keeps its rows and still reproduces. Exit: green.

**Step 3. The report says the stored reason.** `_sensitivity` prints "−1 SE no value (WACC ≤ 0)" from the gap; `_precision` names the same cause in its sentence ("… WACC falls to zero or below …" or "… to terminal growth or below …"). For a run stored before 0013 (no gap row), the report finds the reason the way `reproduce` would: it values the run's own stored assumptions again (deterministic, no data read), so old reports also stop guessing. Tests: the report for each reason prints its words; an old-style run (gap rows deleted) prints the recomputed reason; the existing "No useful precision" test still passes. Exit: green.

**Step 4. Docs.** Build Plan Section 4, M2.1 notes: the reason is stored and reported. After merge: v0.5.2 in `docs/versions.md` with the merge commit.

## Alternatives considered

- *Parse the error message for the cause.* Rejected: a message is for people; rewording it would silently change the report.
- *Keep the reason in the run's free-text notes only.* Rejected: the report would have to parse notes, and Decision 2 keeps facts typed.
- *Store a NULL output row with a reason in `run_outputs`.* Rejected: `value` is `NOT NULL` there and every reader assumes a number; changing that rewrites a table that every run uses.
- *A CHECK constraint on `reason`.* Rejected: SQLite can't change a CHECK in place, so each new code would need a table rebuild (as 0011 did); the code checks the codes on write and read instead.
- *Recompute the reason in the report every time and store nothing.* Possible, since valuing stored rows is deterministic, but then `reproduce` can't catch a change in the cause, and the issue asks for the reason as a stored fact. Kept only as the fallback for runs made before 0013.

## Files

`domains/analysis/financial_math.py`, `domains/analysis/dcf.py`, `domains/analysis/runs.py`, `domains/analysis/report.py`, `shared_kernel/migrations/0013_run_output_gaps.sql`, `tests/analysis/test_financial_math.py`, `tests/analysis/test_dcf.py`, `tests/analysis/test_runs.py`, `tests/analysis/test_report_cli.py`, `docs/build-plan.md`, `docs/versions.md`.

## Review log

(filled after the design review)

## Where the work stopped

- Step 0 written.
