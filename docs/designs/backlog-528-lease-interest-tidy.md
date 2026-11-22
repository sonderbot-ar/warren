# Backlog #528: lease interest follow-ups (a map test, the loader's line numbers)

Issue: https://github.com/sonderbot-ar/warren/issues/528 (from the #526 gatekeeper) · Branch `backlog-528-lease-interest-tidy` · Version v0.10.30 when merged.

Status: Done (v0.10.30, nov.22.2026; PR #530, merge `77fe94c`).

## Problem

1. `test_the_lease_interest_is_read_only_when_the_map_has_it` (`tests/analysis/test_lease_interest.py`) only checks that `finance_lease_interest` is listed in `OPTIONAL_ITEMS`. Nothing runs `math_engine.load_history` through a concept map that lacks the item; only the real-data rebuild of `WMT_2026-10-30_1` covers it. A slip in the gate (`load_history`, the `mapped` set) would pass the unit suite.
2. `load_concept_map` (`domains/fundamentals/concepts.py`) names the file and line on every row error but one: the "a tag limited to some companies can't be priority 1" refusal, moved into the per-item loop by #497, names only the item.

## Plan

**Step 0. This doc.**

**Step 1. The map test and the line numbers.**
- A fixture-database test: Test Corp with a stored `FinanceLeaseInterestExpense` fact for FY2019 (inserted as ingest would store it for Walmart). Read through today's map, the history holds `finance_lease_interest`; read through the map in force before #497 (`91c71ab5…`, archived in `concept_maps/`), it does not, and every other item read is the same. A second case: under the old map with the fact stored, the cost of debt of the year is the debt-only interest.
- The loader keeps each row's file and line, and the priority-1 refusal names it (`concept_map.csv line 57: debt_current: a tag limited to some companies can't be priority 1 beside a tag for every company`). The existing test checks the line is named.

Tests: the two above, plus the stricter message check. Exit: full suite, `ruff check`, `ruff format --check` green; no number, field, code or text changes on any answer, the concept map file and its fingerprint unchanged.

## Alternatives considered

- **Patch `ITEMS` in a unit test instead of a database.** Cheaper, but it would not exercise the `concepts` table query the gate reads, which is what the gatekeeper asked to pin.
- **Carry the line on `ConceptRow`.** It would change a frozen dataclass other code compares; a side list of lines kept by the loader is enough.

## Files to change

`tests/analysis/test_lease_interest.py`, `domains/fundamentals/concepts.py`, `tests/fundamentals/test_concepts.py`, `domains/analysis/reading_rules.md` (a row under v12), this doc; on merge `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` is unchanged (no milestone).

## Product impact

None. No output, code or English text a student sees is added, renamed or removed; only a map-loading error message for developers gains its file and line. Brief questions served: none changed.

## Review notes

Explainer, analyst and professor not run: a test and an error message, with no method or number change (as for #519 and #522). Gatekeeper GO on PR #530: ruff clean, `tests/analysis` and `tests/fundamentals` green (1344 passed), the one changed test is stricter, the new database test fails with the gate in `load_history` removed, rows and lines stay aligned (`zip(..., strict=True)`), the reading-rules fingerprint `622ca36da546` matches its row. Non-blocking: this doc's file list left out `reading_rules.md` (fixed on record).
