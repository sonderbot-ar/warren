# Backlog #172 design: run warnings as codes with parameters

Issue #172 (front-end, from the #141 design review). Branch `backlog-172-run-warning-codes`.

## Problem

A baseline run's warnings are English sentences. `build_inputs` appends them to `EngineResult.warnings` (`domains/analysis/math_engine.py`: stale fundamentals, carried-forward and zero balance items, a balance date that differs, cover-page shares, cost of debt out of bounds, a clipped tax rate, a changed concept map, and the fundamentals layer's coverage warning), `post_checks` adds the valuation's own (`math_engine.post_checks`: a forecast margin outside its history, a thin WACC − terminal growth spread, the same at ERP ± 1 SE), and `run_baseline` adds one line per ERP bound with no value (`runs.py`). They are joined into `runs.notes`, one per line. The what-if passes its child's post-checks on as `run_warning` with the English text only (`whatif.py`). The app can't show these in Spanish without parsing English, which breaks the design principle "no text hard-coded in logic" (`docs/product/design-principles.md`).

## Plan

- **Step 0.** This design doc.
- **Step 1. Codes at the source.** `Coded(code, params, text)` moves from `reported.py` to a new `domains/analysis/coded.py` (re-exported from `reported`, so nothing that imports it changes), because `math_engine` cannot import `reported` (`reported` imports `math_engine`). `EngineResult` keeps its notes as `notes: list[Coded]` (added through `result.warn(code, params, text)`); `warnings` becomes a read-only property with the texts, so every reader is unchanged. `post_check_notes(assumptions, outputs) -> list[Coded]` does the checks; `post_checks` returns their texts, unchanged. `run_baseline` codes the missing-bound lines. Every `text` is byte-for-byte the sentence written today. Params are raw values (fractions as fractions, money in its unit, dates as ISO strings), never formatted, so the app formats them. The codes:

  | Code | Params | From |
  |---|---|---|
  | `coverage_ends` | `ticker`, `cik`, `as_of`, `history_ends`, `note` (the universe file's own English note) | fundamentals coverage warning |
  | `data_warning` | none (text only) | any other warning raised while reading facts |
  | `concept_map_changed` | none | concept map hash differs from the last ingest |
  | `fundamentals_stale` | `last_quarter_end`, `days` | last quarter ended long before `as_of` |
  | `balance_carried_forward` | `balance_date`, `items` [{`item`, `period_end`}] | balance item from an older date |
  | `balance_counted_zero` | `balance_date`, `items` [names] | balance item not reported within a year |
  | `balance_date_differs` | `balance_date`, `last_quarter_end` | |
  | `shares_cover_differs` | `cover_shares`, `diluted_shares`, `tolerance` | |
  | `cost_of_debt_out_of_bounds` | `cost_of_debt`, `low`, `high` | |
  | `tax_rate_clipped` | `tax_rate`, `clipped_to`, `low`, `high` | |
  | `margin_outside_history` | `period`, `margin`, `mean`, `sd`, `sigmas`, `n_quarters` | post-check |
  | `thin_terminal_spread` | `spread`, `threshold`, `terminal_share` | post-check (Gordon only) |
  | `thin_terminal_spread_at_erp_bound` | `bound` (`erp_minus_1se`, `erp_plus_1se`), `spread`, `threshold`, `terminal_share` | post-check (Gordon only) |
  | `no_value_per_share` | `bound`, `reason` (a `REASON_WORDS` code) | ERP bound with no value |
  | `note_text` | none (text only) | a stored line with no code: older runs, or a caller that passed text |

  Tests: each code fires with its params on a fixture that triggers it (the existing triggers in `tests/analysis/test_math_engine.py`), and its `text` equals the old sentence; `post_checks(...) == [n.text for n in post_check_notes(...)]` on every existing post-check fixture. Exit: tests and ruff pass; no stored text changes.

- **Step 2. Store and read them.** Migration 0021 adds `run_notes(run_id, position, code, params JSON, text)`, primary key `(run_id, position)`, foreign key to `runs` with cascade delete. `insert_rows` writes one row per note (a plain string becomes `note_text`), in the same transaction as the run, and still writes `runs.notes` as the texts joined by newlines, so `runs.notes`, the Markdown reports and the reproduce check are unchanged. New call `runs.run_notes(conn, run_id) -> RunNotes(run_id, recorded, notes)`: the stored codes, or for a run stored before 0021 (`recorded: false`) each line of `runs.notes` as `note_text`. Command `python -m domains.analysis notes --run-id R [--json]`. `revalue` stores the child's coded post-checks, and its `run_warning` note gains `warning_code` and `warning_params` beside `new` (the code `run_warning` and `new` keep their meaning). Tests: a stored baseline's `run_notes` texts joined equal `runs.notes`; an old run (row deleted from `run_notes`) answers `recorded: false` with its lines; the migration test on a database with stored runs; the what-if's `run_warning` carries the code; the CLI's JSON. Exit: tests and ruff pass; every existing reproduce test passes.

- **Step 3. Real data.** After the snapshot restore, run a fresh baseline for the eight companies at a date with stored runs, and check that each new run's `runs.notes` equals the text the old code stored for the same company and date (same inputs, same notes) and that every line has a code other than `note_text`. Record the codes seen in this doc. Exit: no text differs.

## Alternatives considered

- **Recompute the codes when read.** Post-checks read only the run's rows, so they could be recomputed; build warnings need the data the run was built from, so this covers only part. Storing is exact and is what #175 did for sources.
- **Backfill stored runs.** A rebuild (as `reproduce` does) would give older runs codes. The issue accepts text for older runs, and the app's first screen makes fresh runs; left as a follow-up issue.
- **Replace `run_warning` with the underlying code.** Cleaner, but renames a field the front-end already reads; adding two params breaks nothing.
- **Code the simulation notes too.** Not asked; follow-up if the app shows them.

## Product impact

Serves design principle "no text hard-coded in logic" for every screen that shows a run (F2's first screen; brief Q3–Q5, Q8 through the what-if). Added: table `run_notes` (migration 0021), call `domains.analysis.runs.run_notes(conn, run_id)` with `to_dict` `{run_id, recorded, notes: [{code, params, text}]}`, the command `notes`, and on the what-if's `run_warning` the params `warning_code` and `warning_params`. The codes in the table above are the words the app needs. Nothing renamed or removed; `runs.notes` and the reports read exactly as before. Older runs answer `recorded: false` with `note_text` lines: show the English text. Effect on M10: its branch must add 21 to the migration lists its tests expect.

## Files to change

`domains/analysis/coded.py` (new), `domains/analysis/reported.py`, `domains/analysis/math_engine.py`, `domains/fundamentals/universe.py` (the coverage warning carries its fields), `domains/analysis/runs.py`, `domains/analysis/whatif.py`, `domains/analysis/__main__.py`, `shared_kernel/migrations/0021_run_notes.sql`, tests under `tests/analysis/` and `tests/shared_kernel/`, migration lists in existing tests, `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (Section 2 roadmap line if any).
