# Backlog #196 design: the coverage warning as a reason code, and only Warren's warnings in run notes

Issue #196 (front-end, from the #172 design review, `docs/designs/backlog-172-run-warning-codes.md`). Branch `backlog-196-coverage-reason`.

Status: In progress (nov.05.2026).

## Problem

1. **The coverage warning carries English the app can't translate.** When a query's as-of date is past the day a company's CIK stopped filing (today only Exxon: CIK 0000034088 stops on 2026-08-03 after the holding-company reorganisation), `domains/fundamentals/universe.py:warn_if_beyond_history` raises a `CoverageWarning`. Since #172 it is coded `beyond_history` with params `ticker`, `cik`, `as_of`, `history_ends` and `note`, but `note` is the universe file's English paragraph (`domains/fundamentals/universe.csv`, XOM row). Team sync (v0.9.15) told the app to "leave it out or show it as is until #196". The two facts a student needs, *why* the history stops and *where it continues*, are only in that prose.
2. **Any library warning becomes a stored run note.** `build_inputs` records every warning raised while reading facts (`domains/analysis/math_engine.py`, the `catch_warnings(record=True)` + `simplefilter("always")` block) and `coded_warnings` (`domains/analysis/coded.py`) stores any it doesn't know as `data_warning`, English text only. A library upgrade (a pandas `FutureWarning`, a sqlite3 `DeprecationWarning`) would add untranslatable lines to every new run with no change to Warren. On real data today there are none (0 `data_warning` lines across 903 runs, #172 results), so nothing stored changes.

## Plan

- **Step 0.** This design doc; roadmap line in team sync.
- **Step 1. Reason and successor in the universe file.** `universe.csv` gains two columns, between `history_ends` and `note`: `reason` and `successor_cik`. `COLUMNS` becomes `ticker, cik, history_ends, reason, successor_cik, note`. XOM's row: `reason` `holding_company_reorganisation`, `successor_cik` `0002115436` (ExxonMobil Holdings Corp, already named in the note). Validation in `load_universe`, every problem reported at once as now: `reason` must be one of `COVERAGE_REASONS` (a closed set in `universe.py`, today `{"holding_company_reorganisation"}`, so the app's catalogue can cover it) and is required when `history_ends` is set and refused when it is not; `successor_cik` is empty or ten digits, differs from `cik`, and needs `history_ends`. `UniverseCompany` gains `reason: str | None` and `successor_cik: str | None`. `CoverageWarning.fields` gains `reason` and `successor_cik` (null when empty); `note` stays as the English fallback, and the warning's English text is byte for byte unchanged, so `runs.notes` and the #172 backfill rule (texts joined equal `runs.notes`) still hold. Tests (`tests/fundamentals/test_universe.py`): XOM's reason and successor; each new validation error; a file with the old four columns is refused with the expected column list; the warning's fields carry both and its text is unchanged; every reason in the file is in `COVERAGE_REASONS`. Exit: tests and ruff pass.
- **Step 2. Stored notes get the fields on read.** Runs stored before this change hold `beyond_history` params without `reason` and `successor_cik` (`run_notes` table, migration 0021). No migration and no rewrite of stored rows: `runs.run_notes` adds the two keys, when absent, from today's universe row matched on the note's own `cik` param (the same company-level fact; it is not a financial number and has no as-of). A row whose `cik` matches no universe row gets both as null. The params a note was stored with are never changed in the database. `reported_period` warnings are computed live and already carry them after Step 1. Tests (`tests/analysis/test_run_notes.py` or the existing #172 file): a stored `beyond_history` row without the keys reads back with them; one with them is returned unchanged; an unknown cik gives nulls; the stored row is untouched. Exit: tests pass.
- **Step 3. Only Warren's warnings become notes.** New `shared_kernel/data_warnings.py` with `class DataWarning(UserWarning)`, the base for warnings Warren raises about the data it reads; `CoverageWarning` subclasses it. `coded_warnings` codes `CoverageWarning` as `beyond_history`, any other `DataWarning` as `data_warning` (text only, as now), and returns every other caught warning separately; `build_inputs` and `reported_period` re-emit those with `warnings.warn_explicit` (same category, file and line) after the `catch_warnings` block, so they still reach the log and pytest but are never stored. `data_warning` stays in `RUN_NOTE_CODES` (a future Warren `DataWarning` without its own code, and any line stored before). Tests (`tests/analysis/test_build_warning_codes.py`): the existing "plain warning is a data_warning" test changes, because the behaviour changes on purpose: a plain `UserWarning` is not a note and is re-emitted (`pytest.warns`); a `DataWarning` subclass is a `data_warning` with its text; `beyond_history` carries the two new params. Exit: full suite and ruff pass.
- **Step 4. Results on real data.** With the snapshot restored: `python -m domains.analysis notes --run-id R --json` on a stored XOM run past 2026-08-03 shows `reason` and `successor_cik`; `reported --ticker XOM --period latest-quarter --as-of 2026-10-30 --json` shows them live; `reproduce --all` and a rebuild of a sample (including an XOM run past the cut-off) still pass; count of `data_warning` lines on new runs stays 0. Results written below.

## Alternatives considered

- **Rewrite stored params with a migration.** Changes stored rows for a fact that belongs to the company, not the run; a read-time fill keeps the database as written and gives the same answer. Rejected.
- **Drop `note` from the params.** The English fallback is useful in the log and in the trace; the app ignores it. Kept.
- **Filter warnings with `simplefilter("ignore")` for non-Warren categories.** Hides them completely; a library deprecation that later breaks a query would arrive with no warning. Re-emitting keeps them visible. Rejected.
- **Successor linking (reading the new CIK's filings).** That is the "later task" the note names; it changes data coverage and is out of this item.

## Files to change

`domains/fundamentals/universe.csv`, `domains/fundamentals/universe.py`, `shared_kernel/data_warnings.py` (new), `domains/analysis/coded.py`, `domains/analysis/math_engine.py`, `domains/analysis/reported.py`, `domains/analysis/runs.py`, tests in `tests/fundamentals/` and `tests/analysis/`, `docs/versions.md`, `docs/team-sync.md`.

## Product impact

- Serves the first screen (brief Q3 and Q4 on an XOM date after 2026-08-03): the coverage warning can be shown in Spanish from `reason` and `successor_cik` with no English. Add `holding_company_reorganisation` to the text catalogue; `COVERAGE_REASONS` is the closed set.
- Adds params `reason` and `successor_cik` to `beyond_history` (run notes, `reported_period` warnings, the what-if's `run_warning` when it is one). Nothing renamed or removed; `note` keeps its meaning (English, for the log).
- Fewer English-only lines: a library warning no longer becomes a `data_warning` note on a new run.
- `universe.csv` has two more columns. The question reader reads only `ticker` from it (`webapp/reader/reading.py`, `tickers()`), so it is unaffected.

## Design review

(to come)
