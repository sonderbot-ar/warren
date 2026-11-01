# Backlog #74: a migration test for 0012 on a database that holds a stored simulation

Issue: https://github.com/sonderbot-ar/warren/issues/74 · Branch `backlog-74-migration-0012-sim` · Version v0.5.7 when merged.

## Problem

Migration 0012 adds `shocks.basis` (NOT NULL, default `growth`). The gatekeeper of PR #72 checked by hand that a database built before 0012, holding a stored two-shock simulation, upgrades cleanly: both shocks read back as `growth`, `reproduce_simulation` still matches, and `PRAGMA foreign_key_check` is empty. CI only tests that 0012 applies to an empty v11 database (`tests/llm/test_calls.py::test_0012_applies_to_a_v11_database`), so a later change to 0012 or to how shocks load could break old simulations without a red test.

## Plan

**Step 1 (one commit).** A test in `tests/analysis/test_montecarlo.py`:

1. Build Test Corp on the current schema, store a baseline run and a two-shock simulation (a margin shock and a risk-premium shock, both growth shocks, the only kind that existed before 0012).
2. Build a second database with migrations 0001–0011 only (copied to a temporary folder, as the existing v11 test does), and copy every row of every table from the first database into it, keeping only the columns the v11 schema has. That is the database a pre-0012 build would have held: `shocks` has no `basis`, and tables added after 0011 do not exist.
3. Apply the remaining migrations; assert 12 and 13 are applied, `foreign_key_check` is empty, both shocks read back with basis `growth`, and `reproduce_simulation` is `ok` with the same number of outputs.

Building the old database by copying rows, rather than by running v0.4 code, keeps the test fast and inside CI; it relies on every pre-0012 column meaning the same thing today, which is what "a migration that only adds" means.

Exit: `pytest`, `ruff check`, `ruff format --check` green. No number changes; no design decision changes.

## Alternatives considered

- *Run the v0.4 code from a git worktree to build the old database.* Rejected: slow, needs git history in CI, and tests old code rather than the migration.
- *Insert hand-written rows for one simulation.* Rejected: it would drift from what `save_simulation` writes; copying real rows does not.

## Files

`tests/analysis/test_montecarlo.py`, `docs/designs/backlog-74-migration-0012-sim.md`, `docs/versions.md` (on merge).

## Review log

- **Gatekeeper** (GO, no blockers): 536 passed, ruff clean, CI green on `cbf05a4`. Confirmed the copy models v11 (columns from the v11 schema, 0012 and 0013 tables absent, only the FTS table and its shadows skipped) and that six breaks of 0012 or of the loader each turn the test red. Ideas not taken in this PR: the stored hash and bands come from today's `save_simulation`, so a change to how a growth shock is hashed would pass here (already covered by `tests/analysis/test_shocks.py`); read `basis` straight from SQL for a clearer failure; share the "build at vN and copy rows" loop for #8 and #34.

## Where the work stopped

- Done. Merged in #99 (`2ab35c7`, v0.5.7) after green CI and a gatekeeper GO.
