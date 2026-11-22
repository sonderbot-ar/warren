# Backlog #507: the WACC's text says its debt weight is book debt

Issue: https://github.com/sonderbot-ar/warren/issues/507 (from the #506 professor review) · Branch `backlog-507-wacc-book-debt` · Version v0.10.25 when merged.

Status: Done (v0.10.25, nov.21.2026; PR #516, merge `534a38a`).

## Problem

The output trace describes the WACC step (`sources.FORMULAS["wacc"]`, `domains/analysis/sources.py:254`) as "cost of equity and after-tax cost of debt, weighted by market equity and debt". The debt weight is the balance sheet's **book** debt (`math_engine._balance`; `whatif.py` notes one row is both the debt weight and the debt subtracted on the way to equity), and the run report already says "market value of equity …, book debt …" (`report.py:107`). Since v0.10.22 the debt card shows the filed fair value of debt beside the book debt, so a student can read "market … debt" as that fair value.

## Plan

**Step 0. This doc.**

**Step 1. The wording.** `FORMULAS["wacc"]` becomes "…, weighted by market equity and book debt". `FORMULAS` is English documentation keyed by code: no run stores the text, no output carries it (the trace carries the code), and the app owns the Spanish words. A test pins the wording (`tests/analysis/test_sources.py`). `sources.py` is inside the reading rules' fingerprint, so `domains/analysis/reading_rules.md` gets a same-version row. No other English text says the debt weight is a market value (searched `domains/` and `webapp/` for "market value", "market weight", "weighted by").

**Step 2. The #515 gatekeeper's two notes** (non-blocking, on the code v0.10.24 just merged): `math_engine.refusal_filings` raises `RuntimeError` instead of a bare `assert` when given filings without a CIK (`python -O` drops asserts, which would let wrong EDGAR links through silently), with its test; the `EngineError` docstring says `cik` is set on every refusal out of the steps, as the code does. Folded in here rather than filed, since both are a line each and touch the same reading-rules row.

Exit: full suite, `ruff check`, `ruff format --check` green; no number changes.

## Alternatives considered

- **Weight by the filed fair value of debt.** It is what the textbook prefers (Koller, Goedhart and Wessels, *Valuation*, 7th ed., cost of capital chapter: market weights, book debt as a proxy when close), but it is a method change: the fair value is filed only for long-term debt, only by three of the eight companies (v0.10.22: Microsoft, Coca-Cola, P&G with gaps), and only at fiscal dates, and it would move every WACC. That belongs in its own backlog item with the analyst's and professor's review, not in a wording fix.

## Files to change

`domains/analysis/sources.py`, `domains/analysis/math_engine.py`, `domains/analysis/reading_rules.md`, `tests/analysis/test_sources.py`, `tests/analysis/test_refusal_codes.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None in output: no code, param or field changes. The front-end team's Spanish text for the `wacc` formula, if it says "deuda" alone, could say "deuda contable" to match (team-sync entry on merge).

## Review notes

Explainer, analyst and professor not run: one English documentation string, the professor's own suggested wording. The gatekeeper reviews the PR.
