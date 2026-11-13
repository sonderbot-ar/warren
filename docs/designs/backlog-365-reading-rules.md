# Backlog #365: a run says which reading rules it used

Issue: https://github.com/sonderbot-ar/warren/issues/365 (front-end request R7) · Branch `backlog-365-reading-rules` · Version v0.9.67 (in progress)

## Problem

Since v0.9.64 (#357) every run stores the fingerprint of the concept map it was made with (`runs.concept_map_sha256`), and the brief (`docs/product/brief.md`, "Two runs of the same date", Q3, Q5, Q8) tells the app to say so once above two runs of one company and `as_of` whose fingerprints differ. But the map only says which tags stand for an item. How Warren picks among those tags' facts, derives a fourth quarter, skips a part tagged as the whole (v0.9.65, #322) or a share count in the wrong unit (v0.9.66, #343) lives in code. A fix there leaves the fingerprint unchanged, so two runs of one date can differ with the same fingerprint, and the app has no field to tell. Every run also stores `code_version` (the git commit), but that changes on every commit, including ones that change nothing a run reads, so comparing it would flag nearly every pair.

The pipeline has the same blind spot: `_same_inputs` (`domains/orchestration/nodes.py`) reuses a stored run when its ingest, map, downloads and choices match today's, whatever code made it. A run read under rules that were fixed since is reused as if current.

## What counts as a reading rule

The code that turns filed and downloaded data into a run's assumption rows, before any valuation math:

- `domains/fundamentals/facts.py`: the point-in-time query, tag ranking, quarter derivation, recasts, the sign and part-as-whole checks.
- `domains/analysis/math_engine.py`: the history built from those facts, the share count and its fallbacks, the market inputs, and the assumption rows themselves.

Not counted: `financial_math.py` and `dcf.py` (they compute outputs from the rows; the reproduce-to-the-cent invariant already pins them), text and lessons (`text.py`, `coded.py`: words, not values), `reported.py` (reported lines for the app, not runs).

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. A version, a fingerprint, and a log that must agree.** New module `domains/analysis/reading_rules.py`:
  - `READING_RULES_VERSION = 1`, an integer the code stores on each run.
  - `RULES_MODULES`: the two files above.
  - `rules_fingerprint() -> str`: SHA-256 over each module's syntax tree, with docstrings removed and line numbers left out, so comments, docstrings and formatting (`ruff format`) don't change it, while any change to code does. The tree is written out by a small walker that skips empty fields, so Python 3.11 (CI) and 3.13 give the same fingerprint (checked in Step 1 on both).
  - `domains/analysis/reading_rules.md`: one row per accepted fingerprint, with the version it belongs to, the date, and what changed and why. A code change that can change what a run reads bumps the version (new row, version + 1); a refactor that cannot adds a row under the same version and says why. Mirrors `concept_maps/CHANGES.md` (#357).
  - Tests (`tests/analysis/test_reading_rules.py`): today's fingerprint has its row, and that row's version is `READING_RULES_VERSION`; versions in the log start at 1, never go down and never skip; `READING_RULES_VERSION` is the highest; the fingerprint ignores a comment, a docstring and reformatting but changes with a changed constant or condition (on a temporary module); the failure message names the fingerprint and what to do.
  - Exit: tests pass on Python 3.11 and 3.13 with the same fingerprint.
- **Step 2. Stored on every run, used by rebuild and the pipeline.**
  - Migration `0023_reading_rules.sql`: `runs.reading_rules_version INTEGER`, NULL or at least 1. Stored runs keep NULL: "not recorded" (made before v0.9.67). No backfill: assigning a version to old commits would be a guess (Known limits).
  - `math_engine._snapshot` adds `reading_rules_version`; `runs.SNAPSHOT_COLUMNS` gains it, so `insert_rows` stores it and a what-if inherits its parent's, as it inherits the map's fingerprint.
  - `Rebuild` gains `rules_version` (the run's, or None) and `older_rules` (true when that is not today's). `reproduce --rebuild` adds "under older reading rules (vN, today vM)" or "reading rules not recorded" to the run's line, so a mismatch on such a run reads as expected rather than as a fault. A rebuild still uses today's code: old code is not kept (Alternatives).
  - `_same_inputs` returns False for a run whose reading rules are not today's (including NULL), so the pipeline builds a new run instead of reusing one read under older rules.
  - The run report's data snapshot line names the reading rules (`vN`, or "not recorded").
  - Tests: a new run stores today's version; a what-if stores its parent's; a stored run with an older or NULL version rebuilds with `older_rules` and the reproduce line says so; `_same_inputs` refuses it; the migration applies to a database with stored runs and leaves them NULL.
  - Exit: full suite green.
- **Step 3. Real data, before merge.** On the restored snapshot: the migration applies; all stored runs read NULL; `reproduce --all` still 903 of 903 to the cent; `reproduce --all --rebuild` gives the same counts as on `main`, with each line now saying "reading rules not recorded"; one fresh run stores version 1.

## Alternatives considered

- **Compare `code_version`.** Already stored, but it changes on every commit, so the app would flag nearly every pair of runs. Rejected as the main field; it stays the fallback for runs with no version.
- **A hand-bumped version with no fingerprint.** Simple, but nothing makes a developer bump it; the first forgotten bump makes the field lie. The fingerprint test makes forgetting fail CI.
- **Fingerprint the raw file bytes.** Every comment or reformat would fail the test. The syntax tree without docstrings changes only when code changes.
- **Keep old code and rebuild through it** (as #357 keeps old maps). Rejected: a map is a few kilobytes of data; old code means old imports, old schema and old dependencies. Out of scope; the version only lets a reader tell the runs apart.
- **Backfill stored runs from their commit.** The covered modules changed in dozens of commits before today, none versioned; any number given now would be invented. NULL says so honestly.

## Known limits

- **A judgement remains.** The test forces a row for every code change, but the developer decides bump or refactor. A wrong "refactor" row would hide a real change; the rebuild check (`reproduce --all --rebuild`) still shows the mismatch, loudly, and the reviewer sees the row in the PR.
- **Two files only.** A change elsewhere that changes rows (say a helper in `domains/market/`) is not caught by the fingerprint; it still shows in the rebuild check. The list can grow.
- **903 stored runs stay "not recorded".** For those the app falls back to `code_version`: equal commits mean the same rules; different commits mean "may differ".
- **Not about outputs.** Output math is pinned by reproduce to the cent, not by this version.

**Point in time.** Unchanged: no query changes. **LLMs.** None. **Decision 11.** No source, company or currency change. **Numbers.** No value, assumption, output or note changes on any stored run.

## Files to change

New `domains/analysis/reading_rules.py` and `domains/analysis/reading_rules.md`, new `shared_kernel/migrations/0023_reading_rules.sql`, `domains/analysis/math_engine.py`, `domains/analysis/runs.py`, `domains/analysis/__main__.py`, `domains/analysis/report.py`, `domains/orchestration/nodes.py`, new `tests/analysis/test_reading_rules.py`, `tests/analysis/test_runs.py`, an orchestration test, this doc; at merge `docs/versions.md`, `docs/team-sync.md` and `docs/product/brief.md` (R7 done).

## Product impact

Serves brief Q3, Q5 and Q8 through "Two runs of the same date" (R7, #365). Adds one run field, `reading_rules_version` (integer, or NULL for runs made before v0.9.67), beside `concept_map_sha256`. Nothing renamed or removed; no note, code or lesson added.

What the app can do with it: two runs of one company and date differ in how filings were read when their `concept_map_sha256` differ **or** their `reading_rules_version` differ. If either run has no version, compare `code_version`: the same commit means the same rules; a different one means they may differ, and the app should say "puede" rather than state it. The brief's sentence "Las dos se pueden reproducir tal como se hicieron" holds for both runs' numbers (reproduce from stored assumptions to the cent); only rebuilding a run from the data needs the old map, which is kept, or the old code, which is not.
