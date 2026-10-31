# Backlog #90: warn when a simulation sample discounts an early period at a rate at or below zero

Issue: https://github.com/sonderbot-ar/warren/issues/90 · Branch `backlog-90-low-wacc-note` · Version v0.5.5 when merged.

## Problem

The Monte Carlo's sample check (`domains/analysis/montecarlo.py`, `_check_samples`) looks only at Y5's discount rate, the one the terminal value uses, and stops the run when it is at or below terminal growth (v0.5.4). The eight quarters and Y3–Y4 are guarded only by `financial_math.discount_factors`, which refuses a rate at or below −100%. A risk-premium shock that ends before Y5 (`domains/analysis/shocks.py`, `apply`, the `cost_of_equity_shift` path) can push a period's WACC to zero or below in some samples, and that period is then discounted with a factor at or above the previous one, without any note.

The arithmetic is valid: a rate of −1% gives a finite discount factor, and the value exists. But a cost of capital at or below zero means an investor would pay to hold the company's risk for that period, which no Phase 1 company's capital costs support; it is almost certainly a shock range typed too wide (for example −900 bp instead of −90 bp). Today such samples feed the p10/p50/p90 silently.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. One place computes the per-period discount rates.** `dcf.compute` builds the rates inline (`dcf.py`, `wacc_at` and `rates`). Move that into `dcf.discount_rates(inp) -> list` (one rate per forecast period, floats or per-sample arrays), used by `compute` and by the Monte Carlo, so the check can never read a different rate from the one the valuation uses. No number changes.
Tests: `discount_rates` equals `fm.wacc` by hand for a run without shifts and for one with a shift on a single period; every existing valuation and reproduce test stays green unchanged. Exit: `pytest`, `ruff check`, `ruff format --check` green.

**Step 2. Count the samples and store a warning.** `montecarlo.low_rate_warning(inp, n) -> str | None` counts the samples with any period from the first quarter through Y4 at a WACC at or below zero, and names those periods. Y5 is left out because `_check_samples` already stops the run there at or below terminal growth, which is above zero for every Phase 1 run. `simulate` returns the bands as before; `save_simulation` calls the new function on the same shocked inputs (same seed, same draws, through a shared helper so the samples are drawn once) and stores the warning as a second line of `simulations.notes`, under the existing band note. The run is not stopped.
Wording: "37 of 10,000 samples discount FY2024Q3–FY2024Q4 at a cost of capital at or below zero; such a rate is almost certainly a shock range typed too wide (check the risk-premium shocks)."
Tests: a risk-premium shock of −1,500 bp at p10 lasting 4 quarters warns with the right count (checked by hand against the draws) and the right periods, and still runs; a mild shock gives no warning; a shock reaching Y5 still stops the run as before; the warning is stored in `notes` and the stored simulation still reproduces to the cent. Exit: green.

**Step 3. Report and command line.** `sim_report.render` gets a "## Warnings" section after the Summary listing every line of `notes` after the band note, or "None.", as the run report already does (`report.py`, "## Warnings"). `simulate` on the command line prints the warning after the result line. Tests: the report shows the warning for the Step 2 case and "None." for a clean one; the CLI prints it. Exit: green.

**Step 4. Docs.** Build Plan M4 "Result" notes the warning; after merge, v0.5.5 in `docs/versions.md`.

## What changes for stored results

No number changes and no stored simulation stops reproducing: `reproduce_simulation` compares shocks and bands, not notes, and the bands come from the same arithmetic. Simulations stored before this version have no warning line, so their report shows "None." under Warnings even if a sample went below zero; running them again with `simulate` shows it.

## Alternatives considered

- *Stop the run, like the Y5 check.* Rejected for now. A rate at or below zero in one early period gives a value that exists, unlike Y5 at or below terminal growth, where the perpetuity does not converge. Stopping would also make any stored simulation with such samples fail `reproduce-sim`, which relaxes an invariant; under CLAUDE.md that is the owner's call. The warning makes the problem visible with no such cost.
- *Drop the bad samples.* Rejected for the reason `_check_samples` gives: dropping samples biases the percentiles.
- *A threshold above zero (for example the risk-free rate).* Rejected: any line above zero is a judgment with no source (the same objection as backlog #84 on the 3-point spread line), while zero has a plain meaning, money later worth as much as or more than money now.
- *A new column instead of a notes line.* Rejected: it needs a migration and a migration test for one sentence; `notes` is already the place the run report reads warnings from.
- *Compute the warning when the report is rendered.* Rejected: it re-runs 10,000 samples to draw a page, and old simulations are rare and can be run again.

## Files

`domains/analysis/dcf.py`, `domains/analysis/montecarlo.py`, `domains/analysis/sim_report.py`, `domains/analysis/__main__.py`, `tests/analysis/test_dcf.py`, `tests/analysis/test_montecarlo.py`, `docs/build-plan.md`, `docs/versions.md`.

## Design review

## Review log

## Where the work stopped

- Step 0 written; design review next.
