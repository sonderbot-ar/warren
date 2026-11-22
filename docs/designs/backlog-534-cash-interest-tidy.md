# Backlog #534: cash interest on debt follow-ups (a short-term borrowings test, an empty-facts guard, the years that move)

Issue: https://github.com/sonderbot-ar/warren/issues/534 (from the #532 gatekeeper) · Branch `backlog-534-cash-interest-tidy` · Version v0.10.32 when merged.

Status: Done (v0.10.32, nov.22.2026; PR #537, merge `4fb8548`, after CI green and a gatekeeper GO).

## Problem

1. Reading-rules row `afdd4f45b319` (v13, #527) says Microsoft's cost of debt moves "for FY2018 on, except FY2024 and FY2025". On real data FY2018 never moves (short-term borrowings of 9,072M at 2017-06-30) and FY2020 never moves (its 10-K tagged no cash interest paid). Rows are never edited.
2. The short-term guard (`math_engine._short_term_at`) is tested only with commercial paper, not with `short_term_borrowings` above zero, the case that keeps FY2018.
3. `debt_only = all(...)` in `math_engine.d8_interest` is True when `interest.facts` is empty. `resolve` always returns facts today, so nothing reaches it, but the guard should not depend on that.

## Plan

**Step 0. This doc.**

**Step 1. The guard, the tests, the row.**
- `debt_only` requires a non-empty fact list.
- Tests in `tests/analysis/test_lease_interest.py`: short-term borrowings above zero at either year end keep the accrual interest (FY2018's 9,072M); short-term borrowings of zero do not count; an interest resolved with no facts never gets the lease interest added (fails without the guard).
- A reading-rules row under v13 for the new fingerprint that states the years that move correctly.

Tests: the three above (the first runs for each year end). Exit: full suite, `ruff check`, `ruff format --check` green; no number, field, code or text changes on any answer.

## Alternatives considered

- **Bump the rules version.** No run reads a different figure (no path returns an empty fact list), so the rules say the version stays.
- **Assert non-empty facts in `Resolved`.** Wider than asked: `Resolved` is built in many places, some of which may legitimately carry no facts (a fallback); a local guard is enough.

## Files to change

`domains/analysis/math_engine.py`, `tests/analysis/test_lease_interest.py`, `domains/analysis/reading_rules.md`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. No output, code or English text a student sees is added, renamed or removed. Brief questions served: none changed.

## Review notes

Explainer, analyst and professor not run: a guard and tests, with no method or number change (as for #519, #522 and #528). Gatekeeper GO on PR #537: ruff clean, 2777 passed, 10 skipped; the empty-facts test fails with main's `math_engine.py`; the short-term tests cover the existing guard (they pass without the change, as expected); version 13 is right (only `resolve` feeds `d8_interest`, always with facts); fingerprint `6a674a866fa1` matches its row. Non-blocking, fixed on record: "the four above" counted a parametrised test twice. The corrected Microsoft years in the row are #527's Step 2 results (`docs/designs/backlog-527-msft-capitalised-interest.md`, Results).
