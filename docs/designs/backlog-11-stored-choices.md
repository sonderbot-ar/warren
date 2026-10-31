# Backlog #11: a rebuild uses the run's own choices

Issue: https://github.com/sonderbot-ar/warren/issues/11 · Branch `backlog-11-stored-choices` · Version v0.5.1 when merged.

## Problem

`runs.rebuild()` builds a stored run's assumption rows again from the data it used and compares them row by row (M2.1). Market downloads are pinned by hash and facts are point-in-time, but the owner's choices (equity risk premium method and first year, terminal growth method, terminal value method) come from today's `domains/analysis/user_assumptions.csv`. Editing that file after a run makes the run fail its rebuild although nothing about the run changed. The rebuild should depend only on what the run stored.

The run already stores each choice: `UserChoice.as_assumption()` writes one `assumptions` row per choice, with `source = 'user'` and the method text `"<value>: set by <who> on <date>. <note>"`. `reproduce()` already relies only on those rows. So the fix needs no new table: `rebuild()` reads the choices back from the run's own rows.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. Read the choices back from a run's rows.**
- `UserChoice.from_assumption(row)` in `math_engine.py`, the exact inverse of `as_assumption()`: it parses the method text with one anchored pattern (value up to the first `": set by "`, `set_on` an ISO date, the note the rest, line breaks allowed). A row that is not a user row, or whose text does not parse, raises `EngineError` naming the row; there is no default.
- `runs.stored_choices(rows)` returns the run's choices from its `source = 'user'` rows whose name is a known choice (`USER_CHOICES`). The values are not checked against today's allowed values: a rebuild rebuilds what the run used, and if today's code no longer supports a stored value, `stored_choices` refuses it (see the review).
- `rebuild(conn, run_id, choices=None, ...)`: with no `choices`, it uses `stored_choices`. A run made before `terminal_method` existed has no such row, so it rebuilds under its own rule with no special case. Passing `choices` stays possible, as an explicit "what if the owner had chosen differently" (the special case for old runs then still applies). The command line (`reproduce --rebuild`) calls `rebuild(conn, run_id)` and so uses the stored choices.
- From the design review: the loader refuses a `set_on` that is not an ISO date and a `set_by` holding `" on "` or `": set by "`, so the writer can only store text the reader accepts. `stored_choices` refuses a run missing a choice it always had (only `terminal_method`, in `CHOICES_ADDED_LATER`, may be absent) and a stored value today's code no longer supports, since the engine does not read every method name. The value comes from the method text, never the `value` column (`erp_first_year` is stored as 1989.0).
- Tests: the round trip `from_assumption(as_assumption(c)) == c` for every row of the checked-in CSV and for a note holding a colon, a full stop, " on " and a line break; a non-user row and an unparsable method are refused; a run rebuilds `ok` after `user_assumptions.csv` is edited (the loader pointed at a changed copy), and a rebuild with the edited choices passed in still shows the difference; a run without `terminal_method` rebuilds `values_ok` with no choices passed; the CLI `reproduce --rebuild` is green on a run after the file changes.
- Exit: `pytest`, `ruff check`, `ruff format --check` green.

**Step 2. Docs.** Build plan Section 4, M2.1 implementation notes, the "**Rebuild.**" bullet: the choices come from the run's own rows; README line on `user_assumptions.csv` says a change affects new runs only. After merge: v0.5.1 in `docs/versions.md` with the merge commit.

## Alternatives considered

- *A new `run_choices` table (migration 0013).* Rejected: it would store the same four facts twice, and runs made before the migration would still need the rows. The rows are already what `reproduce()` trusts.
- *Store the CSV's hash with the run and refuse a rebuild when it changed* (as the concept map does). Rejected: that turns an edit into a refusal, which is the problem; the choices are small enough to store whole, and they already are.
- *Parse nothing and keep today's behaviour, documented.* Rejected: it makes the reproducibility check depend on a file the owner is meant to edit.

## Risks

- The method text is now a format two functions share. The round-trip test fixes it: a change to `as_assumption()` that `from_assumption()` cannot read fails CI.
- A `set_by` holding `" on <ISO date>. "` would parse wrongly: the pattern takes the first such date, so a note may hold dates freely but a name may not. Names in the file are short labels ("owner (sonderbot-ar)"); the round-trip test covers the real file, so an edit that breaks this fails CI.

## Files

`domains/analysis/math_engine.py`, `domains/analysis/runs.py`, `tests/analysis/test_runs.py`, `tests/analysis/test_math_engine.py` (or the closest existing test file), `docs/build-plan.md`, `README.md`, `docs/versions.md`.

## Review log

- **Explainer** (3 blockers, all accepted): the doc claimed `build_inputs` refuses a stale choice, but `erp_method` and `terminal_growth_method` are never read (now `stored_choices` checks every value against `USER_CHOICES`, test); the edited-file test must patch the loader `build_inputs` calls (it now does); the loader let through a `set_on` the reader refuses (now refused, test). Ideas taken: a missing choice is an `EngineError`, not a `KeyError` that would crash the `--rebuild` loop; the empty-note and numeric-value cases are tested. To backlog: say in `reproduce --rebuild` when today's file differs from the run's choices.
- **Analyst** (GO with 1 blocker, accepted): the same writer-stricter-than-reader gap, plus a `set_by` holding `" on "` (both refused by the loader, tests). Ideas taken: value from the text, empty notes, `EngineError` for a missing choice with a comment at `USER_CHOICES`, the build-plan line saying what a rebuild now checks. Not done here: running `reproduce --rebuild` over the stored runs, because this environment has no database; the method format is unchanged since it was written, so they should all parse, and the next run with data checks it.
- **Professor** (GO, no blockers): defensible as recording the inputs a result used (Sandve et al. 2013, rule 1; W3C PROV-DM 2013, "used"; Peng 2011). Ideas: a typed table if a fifth field is ever needed (to backlog); enforce the name limit in the loader (done); say what a rebuild now checks (done); a lesson line on spreadsheets silently changing last month's valuation.

## Where the work stopped

- Done. Steps 0–2 merged in #75 (`740f735`, v0.5.1) after green CI and a gatekeeper GO (496 tests). Review ideas are backlog #76.
