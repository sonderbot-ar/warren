# Backlog #477: the inputs behind an answer, tidy-ups from the gatekeepers

Status: built nov.20.2026 (branch `backlog-477-tidy`). Engine team.

## Problem

The gatekeepers on PR #478 (v0.10.13) and PR #491 (v0.10.17) gave GO with small, non-blocking follow-ups, recorded on #477:

- **Comment item 5.** Two numbers in `inputs._contributions` were computed in place, not in `financial_math`: a quarter's change (`now.value - before.value`) and the amount the quarters leave unexplained (`rest * prior_year.value`, with `rest = point.value - total`). Standing rule: every number goes through deterministic, tested `financial_math`.
- **Comment item 6.** When the year-earlier revenue is not reported or not above zero, `_contributions` returned the growth point with no parts and no note, while a missing quarter carries `contribution_quarter_missing`. The app could not tell "no bars" from "bars not built".
- **Comment item 8.** The #471 design doc listed `tests/analysis/test_financial_math.py`; the property test is in `test_inputs.py`.
- **#491 follow-ups.** A test that `load_pairs` never yields NaN (a NaN miss would never equal itself, so the track record's kept rows would rebuild on every call); `import json` at the top of `run_ranges`; a comment that the kept rows have no size limit (about 550 origins today).

Comment item 7 (the `_shared` equality test) was already done in v0.10.17 (`tests/analysis/test_shared_reads.py`). Items 1 (Caterpillar's working capital, a rule change) and 4 (old runs read under older rules) stay open on #477.

## Plan

**Step 0.** This design doc.

**Step 1. Part values through `financial_math`.** New `fm.difference(current, prior)` and `fm.contribution_amount(contribution, prior_total)` (refuses a prior total at or below zero, as `growth_contribution` does). `_contributions` uses them for `revenue_quarter_contribution.value`, `rest` and `not_in_quarters.value`. A reading-rules row under version 11 (financial_math is fingerprinted; no run reads a different figure). The #471 doc's file list corrected. Tests: property tests (`difference` is current − prior; `contribution_amount` undoes `growth_contribution`), the refusal. Exit: every existing inputs test passes unchanged, so the numbers are identical (both helpers are the same arithmetic).

**Step 2. A coded note for a missing prior year.** `contribution_prior_year_missing` with `{"period": "FY<year−1>"}` on the latest annual growth point when the prior year's revenue is missing or not above zero. Test: a stub reader with no prior line, a zero and a negative one; the point keeps its value, has no parts and carries the note. Exit: the test passes.

**Step 3. Run ranges tidy.** `import json` to the module top; the comment on size and NaN; a test that a NaN stored as a miss comes back from `load_pairs` as no NaN (SQLite stores NaN as NULL) and that two reads compare equal. Exit: the test passes.

## Alternatives considered

- **Leave `now.value - before.value` as plain arithmetic.** It is a subtraction, but the rule is strict and the gatekeeper asked for it; a named helper also documents what the bar is.
- **Make `load_pairs` drop rows whose miss is NULL.** It would change which misses a range uses, a rule change; no stored miss is NULL today. Left as is; the test documents the behaviour the kept rows rely on.

## Files to change

`domains/analysis/financial_math.py`, `domains/analysis/inputs.py`, `domains/analysis/reading_rules.md`, `domains/evaluation/run_ranges.py`, `tests/analysis/test_inputs.py`, `tests/evaluation/test_run_ranges_kept.py`, `docs/designs/backlog-471-inputs-behind.md`; on merge `docs/versions.md`, `docs/build-plan.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q5 (the growth card's quarter bars). One new note code for the Spanish catalogue: `contribution_prior_year_missing` (params `period`), on a latest annual growth point that has no quarter bars because the year before is not reported. Nothing renamed or removed; every number is unchanged. No real-data run: the two helpers are the same arithmetic as the code they replace, and every stored-data test passes unchanged.

## Review notes

Small tidy-up from two gatekeeper reviews; design review by the explainer only (below), PR review by the gatekeeper.
