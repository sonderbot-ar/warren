# Backlog #172 design: run warnings as codes with parameters

Issue #172 (front-end, from the #141 design review). Branch `backlog-172-run-warning-codes`.

## Problem

A baseline run's warnings are English sentences. `build_inputs` appends them to `EngineResult.warnings` (`domains/analysis/math_engine.py`: stale fundamentals, carried-forward and zero balance items, a balance date that differs, cover-page shares, cost of debt out of bounds, a clipped tax rate, a changed concept map, and the fundamentals layer's coverage warning), `post_checks` adds the valuation's own (`math_engine.post_checks`: a forecast margin outside its history, a thin WACC − terminal growth spread, the same at ERP ± 1 SE), and `run_baseline` adds one line per ERP bound with no value (`runs.py`). They are joined into `runs.notes`, one per line. The what-if passes its child's post-checks on as `run_warning` with the English text only (`whatif.py`). The app can't show these in Spanish without parsing English, which breaks the design principle "no text hard-coded in logic" (`docs/product/design-principles.md`).

## Plan

- **Step 0.** This design doc.
- **Step 1. Codes at the source.** `Coded(code, params, text)` moves from `reported.py` to a new `domains/analysis/coded.py` (re-exported from `reported`, so nothing that imports it changes), because `math_engine` cannot import `reported` (`reported` imports `math_engine`). `EngineResult` keeps its notes as `notes: list[Coded]` (added through `result.warn(code, params, text)`); `warnings` becomes a read-only property with the texts, so every reader is unchanged. `post_check_notes(assumptions, outputs) -> list[Coded]` does the checks; `post_checks` returns their texts, unchanged. `run_baseline` codes the missing-bound lines. Every `text` is byte-for-byte the sentence written today. Params are raw values (fractions as fractions, money in its unit, dates as ISO strings), never formatted, so the app formats them. The codes:

  Units: *fraction* means 0.03 for 3% or 3 points (the text may print points or percents; the param never does); *count* is a plain number; dates are ISO strings; item names are the engine's canonical balance names (`BALANCE_ITEMS` and the debt-chain items in `math_engine.py`), which the app's catalogue translates. Every code is in one registry, `coded.RUN_NOTE_CODES`, and a test fails when the engine emits a code outside it (F2's catalogue test can read the same set).

  | Code | Params (unit) | From |
  |---|---|---|
  | `beyond_history` | `history_ends` (date), `ticker`, `cik`, `as_of` (date), `note` (the universe file's English note: the app may leave it out, it adds nothing the other params lack for the sentence) | fundamentals coverage warning; the same code `reported.py` already gives it, which now carries the same params |
  | `data_warning` | none (text only) | any other warning raised while reading facts; none expected (Step 3 checks zero) |
  | `concept_map_changed` | none | concept map hash differs from the last ingest |
  | `fundamentals_stale` | `last_quarter_end` (date), `days` (count), `threshold_days` (count, 135) | last quarter ended long before `as_of` |
  | `balance_carried_forward` | `balance_date` (date), `items` [{`item` (name), `period_end` (date)}] | balance item from an older date |
  | `balance_counted_zero` | `balance_date` (date), `items` [names, sorted, as the text] | balance item not reported within a year |
  | `balance_date_differs` | `balance_date`, `last_quarter_end` (dates) | |
  | `shares_cover_differs` | `cover_shares_adjusted`, `diluted_shares_adjusted` (counts, both after the split factor up to the price date), `tolerance` (fraction) | |
  | `cost_of_debt_out_of_bounds` | `cost_of_debt`, `low`, `high` (fractions) | |
  | `tax_rate_clipped` | `tax_rate`, `clipped_to`, `low`, `high` (fractions) | |
  | `margin_outside_history` | `period` (the run's forecast period key, e.g. `FY2027Q1`), `margin`, `mean`, `sd` (fractions), `sigmas` (count), `n_quarters` (count) | post-check |
  | `thin_terminal_spread` | `spread`, `threshold`, `wacc`, `terminal_growth`, `terminal_share` (fractions; `threshold` is `TERMINAL_SPREAD_WARNING`, 0.03) | post-check (Gordon only); `terminal_share` is the run's output |
  | `thin_terminal_spread_at_erp_bound` | `bound` (`erp_minus_1se` or `erp_plus_1se`; the text's "lower"/"higher" follows from it), `spread`, `threshold`, `wacc` (at the bound), `terminal_growth`, `terminal_share` (at the bound) (fractions) | post-check (Gordon only) |
  | `no_value_per_share` | `bound` (`erp_minus_1se` or `erp_plus_1se`), `reason` (a `REASON_WORDS` code) | ERP bound with no value; baseline only (a what-if reports the same as its own `no_value` note, `whatif.py`) |
  | `note_text` | none (text only) | a stored line with no code: a run the backfill could not match, or a caller that passed text |

  Caught warnings stay de-duplicated by text, keeping the first one's params (the coverage warning fires from two queries, `math_engine.py` around line 334). Every `result.warnings.append(...)` becomes `result.warn(code, params, text)`; `warnings` stays readable as texts.

  Tests: each code fires with its params on a fixture that triggers it (the existing triggers in `tests/analysis/test_math_engine.py`), and its `text` equals the old sentence; `threshold == TERMINAL_SPREAD_WARNING`; an XOM date after 2026-08-03 gives one `beyond_history`; every emitted code is in the registry; `post_checks(...) == [n.text for n in post_check_notes(...)]` on every existing post-check fixture. Exit: tests and ruff pass; no stored text changes.

- **Step 2. Store and read them.** Migration 0021 adds `run_notes(run_id, position, code, params JSON, text)`, primary key `(run_id, position)`, foreign key to `runs` with cascade delete. `insert_rows` writes one row per note (a plain string becomes `note_text`), in the same transaction as the run, in the order of the `runs.notes` join (build warnings, post-checks, missing bounds), and still writes `runs.notes` as the texts joined by newlines, so `runs.notes`, the Markdown reports and the reproduce check are unchanged. New call `runs.run_notes(conn, run_id) -> RunNotes(run_id, recorded, notes)`: the stored codes, or for a run stored before 0021 (`recorded: false`) each line of `runs.notes` as `note_text`. Command `python -m domains.analysis notes --run-id R [--json]`. `revalue` stores the child's coded post-checks, and its `run_warning` note gains `warning_code` and `warning_params` beside `new` (the code `run_warning` and `new` keep their meaning). They come from the post-checks `revalue` computes on every call, so a reused child carries them too. Tests: a stored baseline's `run_notes` texts joined equal `runs.notes`; an old run (row deleted from `run_notes`) answers `recorded: false` with its lines; the migration test on a database with stored runs; the what-if's `run_warning` carries the code; the CLI's JSON. Exit: tests and ruff pass; every existing reproduce test passes.

- **Step 3. Backfill stored runs** (product lead's review: the first screen mostly shows stored runs, `f2-web-app.md`). `runs.backfill_notes(conn, run_id)`: a baseline is rebuilt the way `reproduce` rebuilds it (pinned downloads, its own choices), its post-checks and missing bounds are coded from its stored rows and gaps; a what-if child's post-checks from its stored rows. The coded notes are written to `run_notes` only when their texts joined equal `runs.notes` byte for byte; otherwise nothing is written and the run stays `recorded: false`. Command `python -m domains.analysis notes --backfill --run-id R | --all`. Tests: a stored run with its `run_notes` deleted is backfilled to the same rows; a run whose `runs.notes` was edited is left alone and reported. Exit: tests and ruff pass.

- **Step 4. Real data.** After the snapshot restore and its reproduce check: backfill every stored run, record how many matched, and list the codes seen; fresh baselines for the eight companies at the latest ended day give coded notes with no `note_text` and no `data_warning`. Exit: no stored text changes.

## Alternatives considered

- **Recompute the codes when read.** Post-checks read only the run's rows, so they could be recomputed; build warnings need the data the run was built from, so this covers only part. Storing is exact and is what #175 did for sources.
- **Leave older runs as text** (the first draft). The issue allowed it, but the app's first screen reads stored runs, so they would show in English.
- **Replace `run_warning` with the underlying code.** Cleaner, but renames a field the front-end already reads; adding two params breaks nothing.
- **Code the simulation notes too.** Not asked; follow-up if the app shows them.

## Product impact

Serves design principle "no text hard-coded in logic" for every screen that shows a run (F2's first screen; brief Q3–Q5, Q8 through the what-if). Added: table `run_notes` (migration 0021), call `domains.analysis.runs.run_notes(conn, run_id)` with `to_dict` `{run_id, recorded, notes: [{code, params, text}]}`, the command `notes`, and on the what-if's `run_warning` the params `warning_code` and `warning_params`. The codes in the table above are the words the app needs. Nothing renamed or removed; `runs.notes` and the reports read exactly as before. After the backfill, a run answers `recorded: false` only when its stored text could not be matched: show the English text then. `beyond_history` in `reported` gains `ticker`, `cik`, `as_of` and `note` (added, nothing renamed). Effect on M10: its branch must add 21 to the migration lists its tests expect.

## Files to change

`domains/analysis/coded.py` (new), `domains/analysis/reported.py`, `domains/analysis/math_engine.py`, `domains/fundamentals/universe.py` (the coverage warning carries its fields), `domains/analysis/runs.py`, `domains/analysis/whatif.py`, `domains/analysis/__main__.py`, `shared_kernel/migrations/0021_run_notes.sql`, tests under `tests/analysis/` and `tests/shared_kernel/`, migration lists in existing tests, `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (Section 2 roadmap line if any).

## Design review (nov.04.2026)

- **Explainer.** `beyond_history`/`data_warning` already exist in `reported.py`: taken, reused (one code per sentence). Every append becomes `result.warn`: stated. Which shares value: split-adjusted, named so. Reused what-if child: stated. Step 4 now requires zero `data_warning`. `universe.py` change: it was the first build commit on the branch. 0021 is the next free number after M10's 0018: yes; M10 adds 21 to its lists.
- **Analyst.** Two codes for one sentence: fixed (`beyond_history`). Units per param: added, with a test on `threshold`. Split-adjusted shares: renamed. Dedupe: kept, tested on XOM. `threshold_days`: added. Ideas taken in the doc: item sets, period keys, `bound` gives lower/higher, the what-if's `no_value` vocabulary. A `reason` code and successor CIK for the coverage note, and filtering library warnings: follow-up issue.
- **Professor.** Untranslatable params: `note` is marked as English and optional; Step 4 checks zero `data_warning`. `wacc` and `terminal_growth` added to both spread codes. Registry of codes: taken. Teaching sentence per code (`WARNING_SENTENCES`): follow-up issue, the app's catalogue may own it.
- **Product lead.** Stored runs in English: the backfill moved into this item (Step 3). `bound` values pinned. Registry exported. A group per code (data quality vs valuation): left to the app's catalogue.
