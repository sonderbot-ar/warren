# Backlog #10: warn when the spread is thin at ERP ± 1 SE

Issue: https://github.com/sonderbot-ar/warren/issues/10 · Branch `backlog-10-spread-warning` · Version v0.5.3 when merged.

Status: In progress (oct.31.2026).

## Problem

Under the Gordon terminal value, value depends on 1 / (WACC − g). When the spread WACC − g is under 3 points the terminal value dominates and the run gets a warning (`TERMINAL_SPREAD_WARNING`, `math_engine.post_checks`). The check only looks at the baseline WACC. Each run also stores value per share at ERP − 1 SE and ERP + 1 SE (M2.1). A lower ERP lowers WACC, so at ERP − 1 SE the spread can be thin but still positive: the run then stores a very large value per share with no warning next to it. (At zero or below there is no value, and backlog #9 already notes why.)

The issue also asks for boundary tests: a spread of exactly 3 points (no warning) and one just above it.

**Scope.** The warning is a Gordon rule. Under the value-driver terminal value (the default since M4) the spread no longer drives the value, so no warning is raised there, as today. Whether the value-driver rule should refuse g ≥ WACC is the owner's call (backlog #79) and is not touched here. No stored number changes; only run notes gain a line.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. One WACC function.** `dcf.wacc_from(one)` computes WACC from the single-valued inputs (CAPM cost of equity, then the weighted average), and `dcf.compute` uses it, so the check and the valuation can't disagree. Tests: `wacc_from` equals the valuation's own `wacc` for the test company; existing reproduce tests still pass (no number moves). Exit: `pytest`, `ruff check`, `ruff format --check` green.

**Step 2. The check covers ERP ± 1 SE.** `post_checks` (Gordon only) computes the spread at the base ERP and at ERP ± 1 SE, each from the run's own rows with `erp` replaced (`dcf.with_value`). A shifted spread that is positive and under 3 points adds a note naming the bound, its spread and its stored value per share, e.g. "At ERP − 1 SE, WACC − terminal growth is 1.20 points (below 3): value per share there ($412.10) depends mostly on terminal growth and WACC". A spread at or below zero adds nothing here: that output has no value and #9's note already says why. A row set without `erp_std_error` skips the shifted check. The comparison uses a 1e-12 tolerance so a spread of exactly 3 points, which floating point may land a hair under, counts as 3 and does not warn. Tests: baseline and shifted spreads at 2.9, exactly 3.0 and 3.1 points (only 2.9 warns); a thin spread at ERP − 1 SE warns while the baseline does not; a shifted spread of zero or below adds no spread note; no shifted warning under the value-driver rule. Exit: green.

**Step 3. Docs.** Build Plan, M2.1 notes: the spread warning covers ERP ± 1 SE. After merge: v0.5.3 in `docs/versions.md`.

## Alternatives considered

- *Store WACC at ERP ± 1 SE as outputs.* Rejected: it adds stored outputs (and reproduce work) for a value the check can recompute from the run's own rows.
- *Warn on value per share at ERP − 1 SE being far above the base value.* Rejected: a ratio threshold has no grounding; the spread is the cause and is what the existing rule reads.
- *Only check ERP − 1 SE.* Lower ERP gives the thinner spread, but checking both costs nothing and stays right if a future input (a negative beta) flips the sign.

## Files

- `domains/analysis/dcf.py`: `wacc_from`, used by `compute`.
- `domains/analysis/math_engine.py`: `post_checks` checks the shifted spreads.
- `tests/analysis/test_math_engine.py`, `tests/analysis/test_dcf.py` (or the existing DCF test file).
- `docs/build-plan.md`, `docs/versions.md`.

## Design review

(filled after the review)
