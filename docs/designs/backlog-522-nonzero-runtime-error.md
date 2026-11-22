# Backlog #522: the zero-divisor checks survive `python -O`

Issue: https://github.com/sonderbot-ar/warren/issues/522 (from the #521 gatekeeper) · Branch `backlog-522-nonzero-runtime-error` · Version v0.10.28 when merged.

Status: In progress (nov.22.2026).

## Problem

`math_engine._nonzero` checks with `assert` that its `ratio`, `divisor_item` and `period_kind` params come from their closed sets (`coded.ZERO_DIVISOR_*`), and that one quarter or year comes with its fact while a sum takes none. `python -O` drops every `assert`, so under it a slip in Warren's code would put a param outside the catalogue on a `zero_divisor` refusal, and the app's text catalogue could not cover it. #519 moved the refusal-code checks to `coded.require_code` (a `RuntimeError`) for the same reason. `where_params` (same file) also asserts that it can read a refusal's period; under `-O` a bad label would fail later with a bare `TypeError`.

## Plan

**Step 0. This doc.**

**Step 1. RuntimeError checks.** `_nonzero` raises `RuntimeError("unknown zero_divisor <kind> <value>")` for a param outside its set and `RuntimeError` for a fact on a sum or none on a quarter or year. It does not reuse `require_code`, because that lets `None` through (a refusal may have no code) while these three params are required: `None` is refused. `where_params` raises `RuntimeError("unreadable refusal period ...")`. `RuntimeError`, not `ValueError`, for the reason #519 gives: callers catch `ValueError` as a data refusal, and these are slips in code. Tests: the two existing tests in `tests/analysis/test_refusal_codes.py` now expect `RuntimeError` with the message (stricter than a bare `AssertionError`) and gain a `None` ratio and a sum given a fact; `where_params` refuses three bad labels; a subprocess test runs the checks under `python -O`. A `reading_rules.md` row under v11. Exit: full suite, `ruff check`, `ruff format --check` green; no number, field, code or text changes on any answer.

## Alternatives considered

- **Reuse `require_code`.** One call per param, but it accepts `None`, which would weaken the check the assert made.
- **Leave `where_params`.** It is not a closed set, but it is the last `assert` in production code (`grep -rn "^\s*assert " domains shared_kernel`), and the same `-O` reasoning holds.

## Files to change

`domains/analysis/math_engine.py`, `tests/analysis/test_refusal_codes.py`, `tests/analysis/test_unknown_refusal_code.py`, `domains/analysis/reading_rules.md`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. No output, param, code or English text is added, renamed or removed; every refusal a student can see is unchanged. Brief questions served: none changed.

## Review notes

Explainer, analyst and professor not run: a check's exception type, with no method or number change (as for #519).
