# Backlog #495: a stored miss that is empty is refused, not passed on

Issue: https://github.com/sonderbot-ar/warren/issues/495 (from the #494 gatekeeper) · Branch `backlog-495-empty-miss` · Version v0.10.26 when merged.

Status: PR open (nov.21.2026).

## Problem

`ranges.load_pairs` (`domains/evaluation/ranges.py:206`) reads every revenue and EBIT miss stored with `status = 'ok'` and passes each value on as is. SQLite stores a NaN as NULL, so a NaN miss comes back as `None`; the #494 test `test_a_stored_nan_miss_never_comes_back_as_nan` (`tests/evaluation/test_run_ranges_kept.py:132`) shows it. A `None` (or a stored infinity) would then reach the range maths in `run_ranges`, `track_record`, the M9 report and the pipeline's misses hash, and fail far from its cause, or worse, sort silently.

No stored miss is empty or infinite today: `error_rows` computes every ok miss with `financial_math.log_ratio` or `margin_error`, which refuse a non-finite result. So this is a guard on an invariant, not a fix to a live number.

## Plan

**Step 0. This doc.**

**Step 1. Refuse it.** `load_pairs` checks each pair's two misses: a value that is `None` or not finite raises `RangeError` with code `stored_miss_not_finite` and params `origin_id`, `horizon`, `item` (`revenue` or `ebit`) and `value` (`null`, or the float as stored), naming the first bad row in the read's order. `RangeError` gains `code`, `params` and `coded()`, the same shape as `montecarlo.SimulationError` (backlog #212); the code joins a new `coded.RANGE_REFUSAL_CODES`. The #494 test becomes a refusal test (a stored NaN is refused with its origin and item named); new tests cover an EBIT NULL, a stored infinity, and that a clean database loads exactly as before (same pairs, same `pairs_sha256`).

Exit: full suite, `ruff check`, `ruff format --check` green; no number, pair or hash changes on a clean database.

## Alternatives considered

- **(a) Filter empty misses in the SQL.** It would quietly change which past errors a range uses, and so the ranges and the misses hash, on the day a bad row appears: a rule change hidden in a query. An ok miss that is empty means the store is broken, and the honest answer is to say so.
- **Fix it at write time only.** `error_rows` already can't write one; the guard belongs at the read, where every consumer meets it, since rows can also arrive from an older code version or a restored snapshot.

## Files to change

`domains/evaluation/ranges.py`, `domains/analysis/coded.py`, `tests/evaluation/test_run_ranges_kept.py`, this doc; on merge `docs/versions.md`, `docs/build-plan.md` if needed, `docs/team-sync.md`.

## Product impact

None on any answer: no number, field or note changes. A new refusal code, `stored_miss_not_finite`, can come out of every call that reads past misses (run ranges, track record); it means Warren's own store is damaged, not anything the student did, so the app can show a generic "something is wrong on our side" message for it. Brief questions served: none changed.

## Review notes

Explainer, analyst and professor not run: a guard on stored data with no method or number change. The gatekeeper reviews the PR.
