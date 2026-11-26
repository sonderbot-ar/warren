# Backlog #575: read the newest filed 10-K year once per answer; one style for the start check

Issue: https://github.com/sonderbot-ar/warren/issues/575 (from the #571 gatekeeper) · Branch `backlog-575-newest-year-cache` · Version v0.10.43 when merged.

Status: Done (v0.10.43, nov.24.2026; PR #580, merge `eda10e5`, after CI green and a gatekeeper GO).

## Problem

1. `_cost_of_debt_point` (`domains/analysis/single_values.py`) calls `_newest_filed_year` for every chart year it cannot compute, and each call runs one SQL query on `filing_labels`. The answer depends only on the run's CIK and date, so it is the same for every year of one answer. Speed only; no figure is wrong.
2. `_annual_revenue` tests `f.period_start` for truthiness while `_cost_of_debt_window` tests `f.period_start is not None`. Same result for `date` values, two styles.

## Plan

**Step 0. This doc.**

**Step 1. The cache and the style.**
- `_cost_of_debt_point` reads `(filed, read)` through the existing `_cached(singles, "newest_filed_year", ...)`, kept in `Singles.cache` (one per answer, so one CIK and one date). `_newest_filed_year` itself is unchanged, so its direct tests still read the database.
- `_annual_revenue` tests `f.period_start is not None`.
- Test in `tests/analysis/test_single_values.py`: three refused years (one `no_interest_reported`, two `not_filed_yet`) call `_newest_filed_year` once and keep their reasons; it fails on `main`. The test helper `_singles_on` gains the `cache` dict a real `Singles` has.

Tests: the one above. Exit: full suite, `ruff check`, `ruff format --check` green; no number, field, code or text changes on any answer.

## Alternatives considered

- **Cache inside `_newest_filed_year`.** It would need a `cache` on every caller's object, including the tests' bare namespaces that check the query itself; caching at the one call site that repeats is enough.
- **Cache on the connection or module-wide.** Wrong scope: a run's date and CIK set the answer, and `Singles` is already the per-answer home for such values (`hedge_note_used`, the reader's cells).

## Files to change

`domains/analysis/single_values.py`, `tests/analysis/test_single_values.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. No output, code or English text a student sees is added, renamed or removed; a cost-of-debt answer with several refused years makes one database query fewer per year. Brief questions served: none changed.

## Review notes

Explainer, analyst and professor not run: a cache and a style change with no method or number change (as for #519, #522, #528 and #534).

Gatekeeper GO on PR #580: ruff clean, 2910 passed, 10 skipped; the new test fails on main's `single_values.py` (3 calls, not 1); `Singles` is built per answer in `inputs.py` (`inputs_behind`) and `single_values.py` (`cost_of_debt_notes`) and never reused across runs or dates, so the cache scope is right. Non-blocking idea, not taken: pytest's `monkeypatch.setattr` in place of the hand-written swap in the new test.
