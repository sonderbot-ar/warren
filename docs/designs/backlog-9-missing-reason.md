# Backlog #9: store why a DCF output is missing

Issue: https://github.com/sonderbot-ar/warren/issues/9 · Branch `backlog-9-missing-reason` · Version v0.5.2 when merged.

## Problem

Each baseline run stores value per share at the equity risk premium ± 1 standard error (M2.1). When a shifted ERP leaves the DCF without a value, `dcf.run_outputs` catches the `FinancialMathError` and drops the output (`domains/analysis/dcf.py`, the loop at the end of `run_outputs`). Three places then name the cause without knowing it:

- `report._sensitivity` prints "no value (WACC ≤ growth)";
- `report._precision` says "WACC falls to terminal growth or below";
- `runs.run_baseline` writes the note "WACC ≤ terminal growth".

That was right under the Gordon terminal value (M2), which fails exactly when WACC ≤ g. Since M4 the owner's terminal rule is the value-driver formula NOPAT × (1 + g) / WACC (Structure Guide Decision 4, oct.30.2026); as coded, it refuses only WACC ≤ 0 (`financial_math.value_driver_terminal_value`). Under today's rule the stated cause can be wrong. A report that names the wrong cause teaches the wrong lesson, which matters for a teaching tool (Decision 11). The report also says the missing bound is the lower one; a lower ERP lowers WACC and raises the value, so it is the upper one.

**Out of scope here, sent to the owner (analyst review).** The closed form NOPAT × (1 + g) / WACC comes from summing a perpetuity, which converges only when g < WACC. At g ≥ WACC the code still returns a finite value that does not exist, both for ERP − 1 SE and in the Monte Carlo floor (`montecarlo.py`, floor 0 under the value-driver rule). Enforcing g < WACC there changes stored numbers and the owner's M4 rule, so it is a decision card and backlog issue, not part of this change. This change makes no number different.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. Errors carry a reason code.** `FinancialMathError(message, reason="invalid_input")` gains a `reason` attribute; it stays a `ValueError`, so every existing `except` and `pytest.raises` still works. Codes, set where the error is raised:

| Code | Raised by | Plain words in the report |
|---|---|---|
| `growth_not_below_rate` | `gordon_terminal_value` | WACC ≤ terminal growth |
| `rate_not_positive` | `value_driver_terminal_value` | WACC ≤ 0 |
| `rate_not_above_minus_100` | `discount_factors` | WACC ≤ −100% |
| `invalid_input` | every other check | the error's own message |

`REASONS` in `financial_math.py` is the set of codes; the words a reader sees live in `domains/analysis/text.py` (`REASON_WORDS`, `REASON_SENTENCES`; Decision 11, guardrail 5). An unknown code is refused when the error is made. No number changes: the functions compute exactly as before.
Tests: each of the three raises carries its code; any other raise carries `invalid_input`; the existing `match=` tests still pass. Exit: `pytest`, `ruff check`, `ruff format --check` green.

**Step 2. Store the reason with the run (migration `0013_run_output_gaps.sql`).**

```text
run_output_gaps(run_id REFERENCES runs, name, period, reason, detail, PRIMARY KEY (run_id, name, period))
```

- `dcf.outputs_and_gaps(rows)` returns `(outputs, gaps)`, both keyed by `(name, period)` (period `-` for these values); a gap is `Gap(reason, detail)`, detail the error message. Only the "no value" codes (`growth_not_below_rate`, `rate_not_positive`, `rate_not_above_minus_100`) become gaps; an `invalid_input` error stops the run as before, so a bad input is never stored as a fact. `run_outputs(rows)` stays and returns the outputs only.
- Columns: `reason TEXT NOT NULL`, `detail TEXT NOT NULL`. `save_run` gains a `gaps` argument (default none); `run_baseline` passes the gaps from `outputs_and_gaps`.
- `Reproduction` gains `gap_mismatches` (name, period, stored reason, reason now or none); `ok` needs both lists empty, and the command line prints them.
- `runs.save_run` writes the gap rows in the same transaction as the outputs; `runs.load_gaps` reads them. A reason code outside `REASONS` is refused on write and on read (`ValueError`), so the column stays typed without a CHECK that a new code would force a table rebuild for.
- `reproduce` also compares each stored gap with today's: a gap whose reason changed is a mismatch. A run stored before 0013 has no gap rows; its missing outputs are still checked as before (stored missing, now missing), only the reason isn't compared.
- `run_baseline`'s note names the stored reason ("No value per share at erp minus 1se: WACC ≤ 0").
- The migration is additive (a new table, no rewrite), so an existing database upgrades in place. The runner records versions in `schema_version`; "v12" means migrations up to 0012 applied.
Tests: Gordon at ERP − 1 SE = g gives `growth_not_below_rate`; value-driver with WACC < 0 gives `rate_not_positive`; no gap when both values exist; an `invalid_input` in a sensitivity stops the run; a run stores its gap and its note names the real cause; an unknown code is refused on write and read; reproduce flags a stored gap the code no longer finds; a database at 0012 holding a run upgrades to 0013 and keeps its rows. The three older migration tests that list every migration applied after theirs now list 0013 too. Exit: green.

**Step 3. The report says the stored reason.** `_sensitivity` prints "−1 SE no value (WACC ≤ 0)" from the gap; `_precision` names the same cause in its sentence ("… WACC falls to zero or below …" or "… to terminal growth or below …"). For a run stored before 0013 (no gap row), the report finds the reason the way `reproduce` would: it values the run's own stored assumptions again (deterministic, no data read, under the run's own `terminal_method`), and marks it "(recomputed …)". If no reason can be found it says "reason not found" and names no cause. The precision sentence says the missing bound is the upper one. Tests: the report for each stored reason prints its words and sentence and "upper bound"; a run without gap rows whose rows truly have no value prints the recomputed reason; a missing output with no reason prints "reason not found" and no precision sentence. The old test that deleted an output and expected "WACC ≤ growth" is replaced by these: it asserted the guess this change removes. Exit: green.

**Step 4. Docs.** Build Plan Section 4, M2.1 notes ("**Reproduce.**" bullet): the reason is stored and reported. After merge: v0.5.2 in `docs/versions.md` with the merge commit.

## Alternatives considered

- *Parse the error message for the cause.* Rejected: a message is for people; rewording it would silently change the report.
- *Keep the reason in the run's free-text notes only.* Rejected: the report would have to parse notes, and Decision 2 keeps facts typed.
- *Store a NULL output row with a reason in `run_outputs`.* Rejected: `value` is `NOT NULL` there and every reader assumes a number; changing that rewrites a table that every run uses.
- *A CHECK constraint on `reason`.* Rejected: SQLite can't change a CHECK in place, so each new code would need a table rebuild (as 0011 did); the code checks the codes on write and read instead.
- *Recompute the reason in the report every time and store nothing.* Possible, since valuing stored rows is deterministic, but then `reproduce` can't catch a change in the cause, and the issue asks for the reason as a stored fact. Kept only as the fallback for runs made before 0013.

## Files

`domains/analysis/financial_math.py`, `domains/analysis/text.py` (new), `domains/analysis/dcf.py`, `domains/analysis/__main__.py`, `domains/analysis/runs.py`, `domains/analysis/report.py`, `shared_kernel/migrations/0013_run_output_gaps.sql`, `tests/analysis/test_financial_math.py`, `tests/analysis/test_dcf.py`, `tests/analysis/test_runs.py`, `tests/analysis/test_report_cli.py`, `tests/shared_kernel/test_migration_0013.py` (new), `tests/llm/test_calls.py` and `tests/news/test_store.py` (migration lists), `docs/build-plan.md`, `docs/versions.md`.

## Review log

- **Explainer** (4 blockers, all accepted): store only "no value" reasons and let a bad input stop the run (done, test); the old report test asserts the old guess (replaced, see Step 3); the run note path needs a test (done); docs at Build Plan M2.1 "Reproduce" name the old cause (updated). Gaps filled in the doc: the return shape, `save_run`'s argument, the columns, how versions are tracked, `gap_mismatches`, which words `invalid_input` prints. Ideas taken: the recomputed reason is labelled and tested. Not changed: Build Plan's and the Structure Guide's "terminal growth must be below WACC" checks are right (see the analyst). Idea to backlog: say whether the Monte Carlo keeps the reason code when a sample has no value.
- **Analyst** (NO-GO, 2 blockers): (1) the value-driver closed form is valid only for g < WACC, so at g ≥ WACC the code returns a value that does not exist, at ERP − 1 SE and in the Monte Carlo floor. Accepted as a real defect, but fixing it changes stored numbers and the owner's M4 terminal rule, so it goes to the owner as a decision card and a backlog issue; this change keeps every number and only stops naming a cause it doesn't know. (2) "without a lower bound" is backwards: fixed, test. Ideas to backlog: the ERP is a geometric mean but its standard error is the arithmetic mean's. Taken: the recomputed reason uses the run's own `terminal_method` (it does, through `dcf.inputs`); `rate_not_above_minus_100` is unreachable for real inputs and no test suggests otherwise.
- **Professor** (NO-GO, 1 blocker): reader-facing words were in the math library, against Decision 11 guardrail 5 and Decision 4. Accepted: codes stay in `financial_math.py`, words moved to `text.py`. Ideas taken: a sentence of economics for each reason; stale comments in `dcf.py` rewritten. Kept against advice: the recompute fallback for old runs, because a "reason not recorded" label would leave every existing report without a cause; it is labelled. To backlog: re-base the precision warning, which under the value-driver rule will rarely fire although ERP − 1 SE can still swamp the value. Sources cited: W3C PROV-DM (2013), Sandve et al. (2013), Peng (2011), Rubin (1976), Koller, Goedhart and Wessels (2020) ch. 14, Damodaran (2012) ch. 12.

## Where the work stopped

- Steps 0–3 built (511 tests). Step 4 docs, then PR.
