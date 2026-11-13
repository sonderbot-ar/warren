# Backlog #365: a run says which reading rules it used

Issue: https://github.com/sonderbot-ar/warren/issues/365 (front-end request R7) · Branch `backlog-365-reading-rules` · Version v0.9.67 (in progress)

## Problem

Since v0.9.64 (#357) every run stores the fingerprint of the concept map it was made with (`runs.concept_map_sha256`), and the brief (`docs/product/brief.md`, "Two runs of the same date", Q3, Q5, Q8) tells the app to say so once above two runs of one company and `as_of` whose fingerprints differ. But the map only says which tags stand for an item. How Warren picks among those tags' facts, derives a fourth quarter, skips a part tagged as the whole (v0.9.65, #322) or a share count in the wrong unit (v0.9.66, #343) lives in code. A fix there leaves the fingerprint unchanged, so two runs of one date can differ with the same fingerprint, and the app has no field to tell. Every run also stores `code_version` (the git commit), but that changes on every commit, including ones that change nothing a run reads, so comparing it would flag nearly every pair.

The pipeline has a related blind spot: `_same_inputs` (`domains/orchestration/nodes.py`) reuses a stored run when its ingest, map, downloads and choices match today's, whatever code made it. This change leaves that alone (see the design review: changing it would start paid LLM calls again); it is filed as a follow-up.

## What counts as a reading rule

The code that turns filed and downloaded data into a run's assumption rows: `domains/fundamentals/facts.py` (the point-in-time query, tag ranking, quarter derivation, recasts, the sign and part-as-whole checks) and `domains/analysis/math_engine.py` (the history, the share count, the market inputs, the rows), **and every Warren module they import at their top level, directly or not**, found by walking the imports (`rules_modules()`). Today that is 15 modules, among them `financial_math.py` (the beta and cost-of-debt rows), `domains/market/erp.py`, `yields.py` and `prices.py` (the ERP, the risk-free rate, split adjustment, weekly returns), `fundamentals/quality.py` (`CONSISTENCY_TOLERANCE`) and `dcf.py` (`QUARTERS`, `YEARS`, `SEED`). A new import joins the rules by itself.

Left out, by a written list with a reason each (`NOT_RULES`): `coded.py` (notes as codes and words), `shared_kernel/data_warnings.py` (the warning class), and `reading_rules.py` itself. Modules the engine does not import (`text.py`, `reported.py`, `runs.py`) are not reading rules: they write words, reported lines for the app, and storage.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. A version, a fingerprint, and a log that must agree.** New module `domains/analysis/reading_rules.py`:
  - `READING_RULES_VERSION = 1`, a plain integer (not SemVer) the code stores on each run.
  - `ROOT_MODULES` (the two files), `NOT_RULES` (path to reason), `rules_modules(root)` (the import walk, sorted).
  - `rules_fingerprint(modules=None, root=REPO_ROOT) -> str`: SHA-256 over, for each module in sorted path order, its path, a newline, its syntax tree as text, a newline. The tree loses its docstrings and is written out by a small walker that keeps node and field names, drops line numbers, `ctx`, `kind` and `type_comment`, and skips empty fields. So comments, docstrings and layout (`ruff format`) don't change it, while a code change does: it *detects* a change; only the log row says what the change means. Python 3.11, 3.12 and 3.13 give the same fingerprint (checked by hand in Step 1: `e8cb250579da` on all three). `python -m domains.analysis.reading_rules` prints the version, the fingerprint and the modules.
  - `domains/analysis/reading_rules.md`: a table `| `<first 12 of the fingerprint>` | <version> | <date and PR> | <what changed and why> |`, parsed by `logged_versions()`. In the same commit as the code change: a change that can change what a run reads adds 1 to the version and a row; one that cannot (a refactor, note wording, or only a Python upgrade that changed the syntax tree) adds a row under the same version, saying why. Rows are never edited. Mirrors `concept_maps/CHANGES.md` (#357).
  - Tests (`tests/analysis/test_reading_rules.py`): today's fingerprint has its row, under `READING_RULES_VERSION`, and the failure says what to do (including the Python-upgrade case); the log's versions start at 1 and each row is the same as the one before or one more; `READING_RULES_VERSION` is the highest; no fingerprint twice; the rules include `facts.py`, `math_engine.py`, `erp.py`, `yields.py`, `prices.py`, `quality.py` and `dcf.py`, and none of `NOT_RULES`; the fingerprint ignores a comment, a docstring and parentheses but changes with a constant, a comparison or a sign (on a temporary module); a module imported through another joins the rules and one not imported doesn't.
  - Exit: tests pass on Python 3.11 and 3.13 with the same fingerprint.
- **Step 2. Stored on every run, used by rebuild and the pipeline.**
  - Migration `0023_reading_rules.sql`: `runs.reading_rules_version INTEGER` with `CHECK (reading_rules_version IS NULL OR reading_rules_version >= 1)`. Stored runs keep NULL: "not recorded" (made before v0.9.67). No backfill: assigning a version to old commits would be a guess (Known limits).
  - `math_engine._snapshot` adds `reading_rules_version`; `runs.SNAPSHOT_COLUMNS` gains it, and `insert_rows` builds its column list from `SNAPSHOT_COLUMNS` (analyst), so it stores it, and a what-if takes its parent's row's value (`whatif.py` passes the parent row to `save_rows`), NULL for a NULL parent.
  - `Rebuild` gains `rules_version` (the run's, or None) and `older_rules` (true when that is not today's). `reproduce --rebuild` adds "under older reading rules (vN, today vM)" or "reading rules not recorded" to the run's line, so a mismatch on such a run reads as expected rather than as a fault. A rebuild still uses today's code: old code is not kept (Alternatives).
  - The run report's data snapshot line names the reading rules (`vN`, or "not recorded").
  - Tests: a new run stores today's version; a what-if stores its parent's (and NULL from a NULL parent); the column refuses 0; a run on today's, an older and no version rebuilds with the right `older_rules` and the reproduce line says so; the report names the rules; the migration leaves a stored run NULL (`tests/shared_kernel/test_migration_0023.py`; the other migration tests' expected lists gain 23).
  - Exit: full suite green.
- **Step 3. Real data, before merge.** On the restored snapshot (`20261110T202538Z`): the migration applies; all stored runs read NULL; `reproduce --all` still 903 of 903 to the cent; `reproduce --all --rebuild` gives the same counts as v0.9.64's Step 3 on `main` (903 of 903 to the cent, 821 of 903 identical rows), with each line now saying "reading rules not recorded"; one fresh run stores version 1. Also counted, for the app (product lead): how many stored runs carry `unknown` or a `+dirty` code version.

## Step 3 results (nov.13.2026, snapshot `20261110T202538Z`)

- **The migration applies** to the restored database (schema 22 to 23); all 903 stored runs read NULL.
- **Nothing else moves.** `reproduce --all --rebuild` on this branch: 903 of 903 reproduce to the cent and 821 of 903 rebuild to identical rows, the same counts as on `main` (v0.9.64's Step 3); every line now ends "reading rules not recorded". 2 minutes 40 seconds.
- **A fresh run stores version 1.** KO as of 2026-10-30 stored `reading_rules_version` 1 and rebuilt `ok`, not older; then deleted, so the database is back to 903 runs.
- **For the app's fallback (product lead):** 0 stored runs carry `unknown`, **519 of 903 carry a `+dirty` code version**, and 8 distinct code versions in all. So case (c) says "may differ" for most stored pairs; the rebuild-based backfill (follow-up) is what would quiet it.

## Alternatives considered

- **Compare `code_version`.** Already stored, but it changes on every commit, so the app would flag nearly every pair of runs. Rejected as the main field; it stays the fallback for runs with no version.
- **A hand-bumped version with no fingerprint.** Simple, but nothing makes a developer bump it; the first forgotten bump makes the field lie. The fingerprint test makes forgetting fail CI.
- **Fingerprint the raw file bytes.** Every comment or reformat would fail the test. The syntax tree without docstrings changes only when code changes.
- **Keep old code and rebuild through it** (as #357 keeps old maps). Rejected: a map is a few kilobytes of data; old code means old imports, old schema and old dependencies. Out of scope; the version only lets a reader tell the runs apart.
- **Backfill stored runs from their commit.** The covered modules changed in dozens of commits before today, none versioned; any number given now would be invented. NULL says so honestly. A backfill by rebuild (analyst) is a different claim, "its rows match today's rules", and is filed as a follow-up.
- **Only the two files** (first draft). Rejected at review (analyst, professor): the ERP, risk-free, beta and cost-of-debt rows are computed in modules they import.
- **Stop the pipeline reusing older-rules runs** (first draft). Dropped at review (analyst): it would trigger paid LLM calls on every stored case, which is the owner's call; reuse by rebuilt rows is the follow-up.

## Known limits

- **A judgement remains.** The test forces a row for every code change, but the developer decides bump or refactor. A wrong "refactor" row would hide a real change; the rebuild check (`reproduce --all --rebuild`) still shows the mismatch, loudly, and the reviewer sees the row in the PR.
- **Imports at the top of a module only.** A module imported inside a function, or data a module reads from a file (the concept map has its own fingerprint; `user_assumptions.csv` is stored as the run's choices), is not in the fingerprint. The rebuild check still shows a change there.
- **Note wording in `math_engine.py` counts as code** (analyst): a change to a note's words needs a row under the same version. Some noise, on purpose: no wording change can slip a value change past the test.
- **A future Python can change the syntax tree** without a code change (professor). The test then fails; the fix is a row under the same version naming the Python version.
- **The pipeline still reuses a stored run whatever rules made it** (`_same_inputs`, and `domains/llm/__main__.py` reusing the latest run). Refusing older-rules runs there would rebuild every stored case's baseline, and with it new paid shock proposals, reviews and simulations (analyst, `domains/llm/propose.py` keys proposals on `run_id`). Follow-up: reuse a run when its rows rebuild identically under today's code, which costs nothing.
- **903 stored runs stay "not recorded".** For those the app falls back to `code_version` (Product impact), which is noisy. Follow-up (analyst): mark a stored run "rows match v1" when it rebuilds to identical rows under today's code, with a status like the notes backfill's; that is a check, not a guess.
- **Not about outputs.** Output math is pinned by reproduce to the cent, not by this version.

**Point in time.** Unchanged: no query changes. **LLMs.** None. **Decision 11.** No source, company or currency change. **Numbers.** No value, assumption, output or note changes on any stored run.

## Files to change

New `domains/analysis/reading_rules.py` and `domains/analysis/reading_rules.md`, new `shared_kernel/migrations/0023_reading_rules.sql`, `domains/analysis/math_engine.py`, `domains/analysis/runs.py`, `domains/analysis/__main__.py`, `domains/analysis/report.py`, `domains/orchestration/nodes.py`, new `tests/analysis/test_reading_rules.py`, `tests/analysis/test_runs.py`, an orchestration test, this doc; at merge `docs/versions.md`, `docs/team-sync.md` and `docs/product/brief.md` (R7 done).

## Product impact

Serves brief Q3, Q5 and Q8 through "Two runs of the same date" (R7, #365). Adds one run field, `reading_rules_version` (integer, or NULL for runs made before v0.9.67), beside `concept_map_sha256`. Today's version is `READING_RULES_VERSION` in `domains/analysis/reading_rules.py`, so the app can say which run is current (it is not always the newest: two runs on v1 and v2 while today is v3). Nothing renamed or removed; no note, code or lesson added; the pipeline picks runs as before.

What is true in each case, for the app to word (the front-end team writes the Spanish):

- **(a) The maps differ** (`concept_map_sha256`): the brief's text stands. Both runs can be read again from the reports as they were made, because old maps are kept.
- **(b) The rules versions differ** (both recorded): Warren changed how it reads the reports between them, and the higher version is the corrected reading. Both runs keep their assumptions and recompute to the cent, but the older one can no longer be read again from the reports under its own rules, because old code is not kept. So "Las dos se pueden reproducir tal como se hicieron" is not true for (b) as a student will read it.
- **(c) Either version is NULL:** compare `code_version`. The same commit, with neither `unknown` nor ending `+dirty`, means the same rules. Anything else (different commits, `unknown`, `+dirty`) means they *may* differ: no "cambió", no "corregida" (product lead). This case is noisy: almost any pair with a stored run falls in it until the follow-up backfill.

The run's source line can show "v1" beside the map fingerprint, or "no registradas" for NULL. A row of `reading_rules.md` (what changed and why) has a fixed table layout the app may read for "¿qué cambió?". The field can say "same" while the reading differed only through the limits above (a top-level import missed, a wrong refactor row); the app never states "same", it only stays silent, so it can live with that.

## Design review (nov.13.2026)

- **Explainer: GO.** Asked to pin the hash layout, the log format, the version rule with several rows, the CHECK, and the counts to compare in Step 3: **taken**, all in the plan above.
- **Analyst: NO-GO, two blockers, both taken.** (1) The two files miss code that sets rows (beta and cost of debt in `financial_math.py`, the ERP in `market/erp.py`, the risk-free rate, split adjustment, `CONSISTENCY_TOLERANCE`, `dcf`'s constants), and the doc wrongly said reproduce pins `financial_math`: reproduce re-values stored rows, it never recomputes them. The rules are now the import closure of the two files. (2) Refusing older-rules runs in `_same_inputs` would start new paid shock proposals, reviews and simulations for every stored case: dropped, with reuse by rebuilt rows as a follow-up. Suggestions taken: `insert_rows` built from `SNAPSHOT_COLUMNS`; note-wording churn named; the rebuild-based backfill filed.
- **Professor: NO-GO, one blocker, taken.** The same coverage gap as the analyst's (1). Suggestions taken: "detects" a change rather than "any change does"; a Python upgrade is named in the failure message and Known limits; a plain integer, not SemVer. The method is judged defensible (Sandve et al. 2013, rules 3–4; W3C PROV-O's `prov:Plan` for the rules a run followed). Not taken: a Python column in the log; the row's text names the version when it is the cause.
- **Product lead: NO-GO, two blockers, taken.** (B1) `unknown` and `+dirty` code versions can't mean "same rules". (B2) the brief's "Las dos se pueden reproducir tal como se hicieron" isn't true for a rules pair, and the fallback can only say "puede". Product impact now gives cases (a), (b) and (c). Suggestions taken: where today's version comes from, the source line's wording, and the limits. The pipeline suggestion (S2) no longer applies: the pipeline is unchanged.
