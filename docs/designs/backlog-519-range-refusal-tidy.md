# Backlog #519: a refusal's params are strict JSON, and an unknown code is refused the same way everywhere

Issue: https://github.com/sonderbot-ar/warren/issues/519 (from the #518 gatekeeper) · Branch `backlog-519-range-refusal-tidy` · Version v0.10.27 when merged.

Status: In progress.

## Problem

1. `ranges._finite_miss` (`domains/evaluation/ranges.py:220`) puts the stored float in `params["value"]`. For an infinite miss that is `float('inf')`, which `json.dumps` writes as `Infinity`: not standard JSON, and `json.dumps(..., allow_nan=False)` or a strict parser in the app refuses it. Every other coded param in the engine is a string, an int, a finite float or null.
2. Coded refusal classes check their code two ways: `RangeError` raises `RuntimeError` on an unknown code, while `montecarlo.SimulationError`, `math_engine.EngineError`, `market.store.MarketDataError` and `simulations._note` use `assert`, which `python -O` drops, so an unknown code would reach the app's text catalogue silently.
3. (Front-end, not this track.) The app's catalogue needs a text for `stored_miss_not_finite`.

## Plan

**Step 0. This doc.**

**Step 1. Strict JSON for the miss.** `params["value"]` becomes `null` when the stored miss is empty and the float's text otherwise (`"inf"`, `"-inf"`, `"nan"`). The English text is unchanged. Tests: the #495 parametrised test expects the string; a new test checks `json.dumps(err.params, allow_nan=False)` works for each bad value.

**Step 2. One check for a code.** New `coded.require_code(code, allowed, kind)` raises `RuntimeError("unknown <kind> code ...")` when `code` is not None and not in `allowed`. `RangeError`, `SimulationError`, `EngineError`, `MarketDataError` and `simulations._note` use it. `RuntimeError`, not `ValueError`, because every one of these error classes is a `ValueError` (or caught as one) and an unknown code is a programming slip, which must not be caught and shown as a data refusal. Tests: each class refuses an unknown code with `RuntimeError`, and the check holds under `python -O` (a subprocess run).

Exit: full suite, `ruff check`, `ruff format --check` green; no number, field, code or text changes on any answer.

## Alternatives considered

- **`null` plus a `kind` param for item 1.** Two fields for one fact; the string keeps one param with the same name and is what the issue proposed first.
- **Keep `assert` and drop the `RuntimeError`.** `assert` vanishes under `-O`; a check the app relies on should not depend on how Python was started.

## Files to change

`domains/evaluation/ranges.py`, `domains/analysis/coded.py`, `domains/analysis/montecarlo.py`, `domains/analysis/math_engine.py`, `domains/market/store.py`, `domains/orchestration/simulations.py`, `tests/evaluation/test_ranges_empty_miss.py`, `tests/analysis/test_refusal_codes.py` and `tests/analysis/test_montecarlo.py` (their unknown-code tests now expect `RuntimeError` instead of `AssertionError`), a new `tests/analysis/test_unknown_refusal_code.py`, `domains/analysis/reading_rules.md` (a row under v11: no run reads a different figure), this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

`stored_miss_not_finite`'s `value` param is now `null` or a string (`"inf"`, `"-inf"`), never a float, so its refusal survives strict JSON. No other output changes. Item 3 of #519 (a generic "something is wrong on our side" text for this code) stays with the front-end team. Brief questions served: none changed.

## Review notes

Explainer, analyst and professor not run: a param's type and a code check, with no method or number change.
