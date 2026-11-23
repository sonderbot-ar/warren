# Backlog #548 and #549: a stale concepts table gives one coded refusal, and the no-caveat path is pinned

Issues: https://github.com/sonderbot-ar/warren/issues/548 and https://github.com/sonderbot-ar/warren/issues/549 (both from the #547 review) · Branch `backlog-548-stale-concepts` · Version v0.10.36 when merged.

Status: In progress (nov.23.2026).

## Problem

1. **#548.** A database whose `concepts` table was not synced since a map item was added (an older snapshot, a local database) makes `get_facts` raise a bare `ValueError("Not in the concept map: [...]")` (`domains/fundamentals/facts.py`, `_rows_by_period`). The single-value paths of `inputs_behind` (`_cost_of_debt` through `_effective_rate` for J&J's stated rate from FY2018, and `_debt_fair_value`) read reported-only items and catch only `EngineError`, so the error escapes uncoded: the app gets a crash, not a refusal, and the message does not say how to fix it.
2. **#549.** Nothing unit-tests that a company with no row in `interest_caveats.csv` gets exactly the cost-of-debt notes it got before #547. Only a real-data check covered it.

## Plan

**Step 0. This doc.**

**Step 1. One coded error for an unsynced table (#548).**
- `facts.ConceptsNotSyncedError(ValueError)` with `code` `concepts_not_synced` and `params` `{"missing": [names, sorted]}`, raised when every unknown name is in the concept map files (so the table, not the caller, is behind); a name in neither stays the plain `ValueError` it was (a caller's typo is not a stale table). Its message still starts "Not in the concept map" and adds that the table is older than the map files and to run `python -m domains.fundamentals ingest --all`. A `ValueError`, so every caller that catches `ValueError` today still does.
- `coded.OTHER_REFUSAL_GROUPS = {"concepts_not_synced": "setup"}` and `text.refusal_lesson` reads it, so the app shows the `setup` group's title and words (product lead). Kept apart from `REFUSAL_GROUPS`, whose codes are exactly the ones a run's build raises (`test_refusal_codes`).
- `inputs_behind` turns it into `InputsError` with the same code and params (the call's refusals are coded, `years_out_of_range`, `output_not_in_run`, `run_not_found`), so the CLI and the app get one coded refusal instead of a traceback. The single-value paths do not catch it: a stale table is the operator's problem, not a missing point, so marking the J&J years "not computable" would hide it.
- Tests: `get_facts` on a database with `debt_effective_rate` deleted from `concepts` raises `ConceptsNotSyncedError` with the code, params and command; `inputs_behind` on a J&J-like run (the #542 test company) with the rate item removed from the table raises `InputsError` code `concepts_not_synced`, not a bare `ValueError`; the same with `debt_fair_value` removed (the #481 path) on a plain run.

Exit: the new tests fail on `main` (bare `ValueError`, no code) and pass here.

**Step 2. The no-caveat path pinned (#549).**
- A parametrised test over every universe ticker with no row in the shipped `interest_caveats.csv`: build the cost-of-debt cell for the test company twice, once with `caveat_for` patched to return None and once with `caveat_for` answering as the shipped file does for that ticker, with interest halved so the years carry the `below_risk_free` note; assert the cell notes and every point's notes are identical (codes, params, text). A guard asserts at least one non-empty note list, so the test cannot pass on empty notes.

Exit: full suite, `ruff check`, `ruff format --check` green. No number, note or text changes on any answer.

## Alternatives considered

- **A startup check that the table matches both map files** (#548 option 2). Every entry point would pay a query, and a check only at app start would still let a CLI run crash. The refusal where the table is read covers every path at no cost; the check stays possible later (#359 item 2).
- **Catch the error in each single-value path and mark the point missing.** Hides an operator problem as a data gap ("no rate stated") on exactly the years the note exists for. Rejected.
- **An `EngineError` code.** `EngineError` codes are a run's refusals (`coded.ENGINE_REFUSAL_CODES`) and their catalogue is for students; this one is for the person running Warren, and the run build already surfaces any `ValueError`. Kept in fundamentals, mapped only where the call is coded.

## Files to change

`domains/fundamentals/facts.py`, `domains/analysis/inputs.py`, `tests/fundamentals/test_facts.py`, `tests/analysis/test_single_values.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Review notes

Product lead on *Product impact*: CHANGES, all accepted. (1) Put the code in the brief's `setup` group (`docs/product/brief.md`, "When an estimate can't be built"), not a generic text: done through `coded.OTHER_REFUSAL_GROUPS`, since adding it to `REFUSAL_GROUPS` would break `test_every_catalogued_code_is_raised_and_every_raised_code_is_catalogued` (a run's build never raises it). (2) The app never names the `missing` items (#297): said below. (3) Add the code to the Spanish catalogue list in the team-sync entry: done on record. Explainer, analyst and professor not run: an error path and a test, with no method or number change (as for #519, #522, #534).

## Product impact

One refusal code added to `inputs_behind` (`InputsError.code`): `concepts_not_synced`, params `missing` (a list of item names). A student never reaches it on a synced database. It belongs to the brief's `setup` group (`coded.OTHER_REFUSAL_GROUPS`; `refusal_lesson` returns that group's lesson), so the app shows the group's title and "Esto no depende de ti…" text, adds the code to its Spanish catalogue, and logs the English message. The app never names the `missing` items: they are engine item names whose Spanish labels wait on #297. Nothing renamed or removed; no number, note or text changes. Brief questions served: none changed (Q3 and Q5's input charts keep working; on a stale database they now refuse cleanly instead of failing).
