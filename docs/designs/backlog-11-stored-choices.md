# Backlog #11: a rebuild uses the run's own choices

Issue: https://github.com/sonderbot-ar/warren/issues/11 · Branch `backlog-11-stored-choices` · Version v0.5.1 when merged.

## Problem

`runs.rebuild()` builds a stored run's assumption rows again from the data it used and compares them row by row (M2.1). Market downloads are pinned by hash and facts are point-in-time, but the owner's choices (equity risk premium method and first year, terminal growth method, terminal value method) come from today's `domains/analysis/user_assumptions.csv`. Editing that file after a run makes the run fail its rebuild although nothing about the run changed. The rebuild should depend only on what the run stored.

The run already stores each choice: `UserChoice.as_assumption()` writes one `assumptions` row per choice, with `source = 'user'` and the method text `"<value>: set by <who> on <date>. <note>"`. `reproduce()` already relies only on those rows. So the fix needs no new table: `rebuild()` reads the choices back from the run's own rows.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. Read the choices back from a run's rows.**
- `UserChoice.from_assumption(row)` in `math_engine.py`, the exact inverse of `as_assumption()`: it parses the method text with one anchored pattern (value up to the first `": set by "`, `set_on` an ISO date, the note the rest, line breaks allowed). A row that is not a user row, or whose text does not parse, raises `EngineError` naming the row; there is no default.
- `runs.stored_choices(rows)` returns the run's choices from its `source = 'user'` rows whose name is a known choice (`USER_CHOICES`). The values are not checked against today's allowed values: a rebuild rebuilds what the run used, and if today's code can no longer build it, `build_inputs` says so.
- `rebuild(conn, run_id, choices=None, ...)`: with no `choices`, it uses `stored_choices`. A run made before `terminal_method` existed has no such row, so it rebuilds under its own rule with no special case. Passing `choices` stays possible, as an explicit "what if the owner had chosen differently" (the special case for old runs then still applies). The command line (`reproduce --rebuild`) calls `rebuild(conn, run_id)` and so uses the stored choices.
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

## Where the work stopped

- Step 0 written (oct.31.2026).
