# Backlog #10: warn when the spread is thin at ERP ± 1 SE

Issue: https://github.com/sonderbot-ar/warren/issues/10 · Branch `backlog-10-spread-warning` · Version v0.5.3 when merged.

Status: Done (oct.31.2026; merged in PR #83, merge commit `b6756a8`, v0.5.3).

## Problem

Under the Gordon terminal value, value depends on 1 / (WACC − g). When the spread WACC − g is under 3 points the terminal value dominates and the run gets a warning (`TERMINAL_SPREAD_WARNING`, `math_engine.post_checks`). The check only looks at the baseline WACC. Each run also stores value per share at ERP − 1 SE and ERP + 1 SE (M2.1). A lower ERP lowers WACC, so at ERP − 1 SE the spread can be thin but still positive: the run then stores a very large value per share with no warning next to it. (At zero or below there is no value, and backlog #9 already notes why.)

The issue also asks for boundary tests: a spread of exactly 3 points (no warning) and one just above it.

**Scope.** The warning is a Gordon rule. Under the value-driver terminal value (the default since M4) the spread no longer drives the value, so no warning is raised there, as today. Whether the value-driver rule should refuse g ≥ WACC is the owner's call (backlog #79) and is not touched here. No stored number changes; only run notes gain a line.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. The check covers ERP ± 1 SE.** Under the Gordon rule, `post_checks` revalues the run's own rows at ERP − 1 SE and ERP + 1 SE (`dcf.value(dcf.with_value(rows, "erp", shifted))`, the same code path as the stored sensitivity, so the check and the stored value can't disagree) and reads that valuation's WACC and terminal share. A shifted spread that is positive and under 3 points adds a note naming the bound, the spread and the terminal share there, e.g. "At ERP − 1 SE, WACC − terminal growth is 1.20 points (below 3): terminal value is 91% of enterprise value there, so this bound mostly shows how the terminal value reacts to the lower ERP". The wording names the ERP as the input that moved (analyst review): at a bound, terminal growth is fixed and only the ERP changed. A revaluation that has no value (spread at or below zero) adds nothing here: #9's note already says why. A row set without `erp_std_error` skips the shifted check; a stored run always has one (`dcf.outputs_and_gaps` refuses rows without it before `post_checks` runs), so the skip serves direct callers and tests only. A note is written only when the revaluation returns a value, which under Gordon means WACC > g, so "positive" needs no separate test; a revaluation that raises `FinancialMathError` adds nothing. The comparison is `spread < TERMINAL_SPREAD_WARNING - 1e-12` in both the base and the shifted check, so a spread of exactly 3 points, which floating point may land a hair under, does not warn. The +1 SE note reads the same with "ERP + 1 SE" and "higher ERP". Tests: base and shifted spreads at 2.9, exactly 3.0 and 3.1 points (only 2.9 warns); a thin spread at ERP − 1 SE warns while the base does not, and the note's terminal share equals the shifted valuation's; a shifted spread at or below zero adds no spread note; no shifted note under the value-driver rule or without `erp_std_error`. Exit: `pytest`, `ruff check`, `ruff format --check` green.

**Step 2. Docs.** Build Plan, M2.1 notes: the spread warning covers ERP ± 1 SE. After merge: v0.5.3 in `docs/versions.md`.

**Expected frequency (analyst review).** Under Decision 7, terminal growth equals the risk-free rate, so the spread is about E/V × β × ERP minus a small debt term. At ERP − 1 SE (about 2 points of ERP) no Phase 1 company keeps a 3-point spread, so on a Gordon run the note will appear almost every time. That is accepted on purpose: it is true of every such run, and it is the thing a reader of the "−1 SE" number most needs to know (that bound is mostly terminal value). Gordon is opt-in since M4 (value-driver is the default, Structure Guide Decision 4), so the note shows only on runs that choose Gordon. Runs already stored keep their notes; notes are written when a run is made.

**Shocked row sets.** `post_checks` reads row sets only. A Monte Carlo cost-of-equity shift lives in the simulation's inputs, not in the rows, so it never reaches this check.

## Alternatives considered

- *Store WACC at ERP ± 1 SE as outputs.* Rejected: it adds stored outputs (and reproduce work) for a value the check can recompute from the run's own rows.
- *A separate WACC-only function for the check.* Tried first and dropped after the professor's review: revaluing with `dcf.value` gives the WACC and the terminal share from the exact path that made the stored number, with no new function.
- *One fixed sentence in the report instead of a run note.* Possible (analyst), but the note carries the run's own spread and terminal share, and the base spread warning is already a note; keeping both in one place reads better.
- *Warn on value per share at ERP − 1 SE being far above the base value.* Rejected: a ratio threshold has no grounding; the spread is the cause and is what the existing rule reads.
- *Only check ERP − 1 SE.* Lower ERP gives the thinner spread, but checking both costs nothing and stays right if a future input (a negative beta) flips the sign.

## Files

- `domains/analysis/math_engine.py`: `post_checks` checks the shifted spreads.
- `tests/analysis/test_math_engine.py`.
- `docs/build-plan.md`, `docs/versions.md`.

## Design review

Explainer, analyst and professor, oct.31.2026, on the first draft.

- **Analyst** (NO-GO, 2 blockers, both accepted): the note fires on nearly every Gordon run because terminal growth = risk-free rate. Accepted on purpose and stated under "Expected frequency". The first wording blamed "terminal growth and WACC" when only the ERP moved; reworded, and the note now carries the terminal share at the bound. Ideas filed as backlog issues: a source for the 3-point threshold; the ERP's SE is the arithmetic mean's but is applied to the geometric premium (already part of #80, so not filed again).
- **Professor** (GO): drop the WACC-only function and revalue instead; give the shifted note the terminal share like the base note; say Gordon is opt-in. All three done.
- **Explainer** (5 gaps, all answered): the `erp_std_error` skip is for direct callers only; the shifted WACC comes from the revaluation; the note no longer cites a value that may not exist; the comparison and its tolerance are spelled out for both checks; "positive" means the revaluation returned a value. Shocked row sets are addressed above; reproduce does not compare notes (`runs.reproduce` compares assumptions, outputs and gaps).
