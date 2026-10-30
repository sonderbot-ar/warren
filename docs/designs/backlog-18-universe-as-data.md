# Backlog #18: the company list as data

Issue: https://github.com/sonderbot-ar/warren/issues/18 · Branch `backlog-18-universe-as-data` · Version v0.3.1 when merged.

## Problem

Decision 11, guardrail 2: companies are data, not code. The Phase 1 list (`PHASE1_UNIVERSE`) is a Python literal in `domains/fundamentals/universe.py`, so adding a company, or pinning a CIK, needs a code change. Phase 2 starts with a LatAm company; that should be one new row.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. `universe.csv` and its loader.**
- New `domains/fundamentals/universe.csv` with columns `ticker,cik,history_ends,note`, one row per company, the same eight companies in the same order, XOM keeping its pinned CIK, history end and note.
- `load_universe(path)` in `universe.py` reads and validates it, reporting every problem at once (the `load_concept_map` idiom): exact columns; ticker non-empty, upper case, unique; `cik` empty or ten digits; `history_ends` empty or an ISO date; `history_ends` needs a `cik` (the pin is what the end date refers to); wrong field counts.
- `PHASE1_UNIVERSE` stays as a module-level list, now `load_universe()`, so its importers (`fundamentals`, `analysis` and `market` command lines, evaluation cases) do not change. `get_universe_company` and `warn_if_beyond_history` are unchanged.
- Tests: the CSV yields exactly the list the literal held (tickers, order, XOM fields); each validation rule fails with a message naming the line; a new company row needs no code (a temp CSV with a ninth row loads). The existing universe tests stay as they are.
- Exit: `pytest`, `ruff check`, `ruff format --check` green; no ticker literal left in `universe.py`.

**Step 2. Docs.** Build plan M1 universe line points at the CSV; Structure Guide Decision 11 guardrail 2 marked as done for the Phase 1 list; versions row after merge.

## Alternatives considered

- *A database table.* Rejected for now: the list is reference data edited by hand and reviewed in PRs; a checked-in CSV diff is easier to review than a migration, and every other hand-kept list in Warren (concept map, known gaps, cases, guidance, aliases) is a CSV. A table can be synced from it later, as `concepts` is.
- *Add currency, country and accounting-standard columns now.* Deferred: guardrail 3 applies to tables that hold money, and the universe holds none. The IFRS adapter in Phase 2 will know what it needs; guessing the columns now risks the wrong ones. Recorded in the PR as a backlog idea.

## Files

`domains/fundamentals/universe.csv` (new), `domains/fundamentals/universe.py`, `tests/fundamentals/test_universe.py`, `docs/build-plan.md`, `docs/structure-guide.md`, `docs/versions.md`.

## Where the work stopped

- (filled in as steps land)
