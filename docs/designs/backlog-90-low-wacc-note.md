# Backlog #90: warn when simulation samples imply a negative risk premium or a rate at or below zero

Issue: https://github.com/sonderbot-ar/warren/issues/90 · Branch `backlog-90-low-wacc-note` · Version v0.5.5 when merged.

## Problem

The Monte Carlo's sample check (`domains/analysis/montecarlo.py`, `_check_samples`) looks only at Y5's discount rate, the one the terminal value uses, and stops the run when it is at or below terminal growth (v0.5.4). The eight quarters and Y3–Y4 are guarded only by `financial_math.discount_factors`, which refuses a rate at or below −100%. A risk-premium shock (`domains/analysis/shocks.py`, `apply`, the `cost_of_equity_shift` path) adds to the cost of equity period by period, and nothing looks at what it leaves behind. Two things can go wrong, silently:

1. **A negative risk premium.** A shift larger than β × ERP leaves the cost of equity at or below the risk-free rate. For a company with β above zero, CAPM rules that out: investors are paid for bearing market risk, never charged for it (Sharpe 1964, *Journal of Finance* 19; Brealey, Myers and Allen, *Principles of Corporate Finance*, ch. 8; Damodaran, *Investment Valuation*, 3rd ed., ch. 8, treats a cost of equity below the risk-free rate as an error). For KO, JNJ and PG (β about 0.5 to 0.6) a −300 bp shock already removes the whole premium.
2. **A discount rate at or below zero.** Money later is then worth as much as or more than money now. The arithmetic still works (a finite factor at or above the previous one), so the value exists, but no Phase 1 company's capital costs support it.

Both are almost certainly a shock range typed too wide. Today such samples feed the p10/p50/p90 with no note. They also matter more than their count suggests: a lower rate in Y3 or Y4 also scales the present value of the terminal value (`financial_math.enterprise_value`, `factors[-1]`), so these samples sit in the upper tail of value. Once they are 10% of samples they can set the p90, and at 50% the p50.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. One place computes the per-period rates.** `dcf.compute` built the rates inline. Move that into `dcf.discount_rates(inp) -> list` (one WACC per forecast period, floats or per-sample arrays) and `dcf.base_wacc(inp)`, used by `compute` and by `_check_samples` for Y5, so a check can never read a different rate from the one the valuation uses. Step 2 adds `dcf.costs_of_equity(inp)` beside them. No number changes.
Tests: `discount_rates` equals WACC by hand for a run with debt, without shifts and with a shift on one quarter only; every existing valuation and reproduce test stays green unchanged. Exit: `pytest`, `ruff check`, `ruff format --check` green.

**Step 2. Check every sample's rates and store the result.**
- `dcf.costs_of_equity(inp) -> list`: the cost of equity per period with its shift; `discount_rates` is built from it.
- `montecarlo.rate_warnings(shocked, n) -> list[str]` takes the *shocked* inputs (per-sample arrays) and makes up to two checks over every period, Y5 included (it costs nothing and stays right if the risk-free rate, and so terminal growth, is ever at or below zero): a cost of equity at or below the risk-free rate, and a WACC at or below zero. For each check that any sample fails, one line: the number of samples that fail it in at least one period, their share, and the periods where at least one sample fails, in period order, comma-separated. If the share is 10% or more the line adds that these samples can set the p90 of value (lower rates raise the value of positive cash flows), and at 50% or more the p50.
  Example: "2,611 of 10,000 samples (26.1%) put the cost of equity at or below the risk-free rate, a negative risk premium, in FY2024Q3, FY2024Q4, FY2025Q1, FY2025Q2. CAPM rules that out for a company with a beta above zero: check the risk-premium shocks' ranges. That many can set the p90 of value."
- The draws are made once. A private helper `_shocked(rows, shock_list, n, seed)` returns the baseline inputs and the shocked inputs; `simulate_checked(rows, shock_list, n, seed) -> (bands, warnings)` uses it, runs `_check_samples` (which still stops the run for impossible drivers and Y5 at or below growth), values the samples and returns the bands and `rate_warnings`. `simulate` returns `simulate_checked(...)[0]`, so its callers, `reproduce_simulation` among them, are unchanged.
- `save_simulation` uses `simulate_checked` and stores `simulations.notes` as lines: the existing band note first, then each warning, or, when none fires, the line "rate check: no sample has a cost of equity at or below the risk-free rate or a discount rate at or below zero". The run is never stopped by these checks.
Tests: with the test company (cost of equity 10%, no debt, so WACC = cost of equity), a risk-premium shock of −1,500 / −500 / 0 bp lasting 4 quarters with no decay fails both checks in exactly those 4 quarters. The negative-premium count equals the number of the same seed's draws whose magnitude is at or below −600 bp (β × ERP = 6%), worked out in the test from the documented generator; and, independently, it is within 4 standard errors of the split-normal probability P(m ≤ −600) = Φ(−100 / (1000 / 1.2816)) ≈ 0.449. The WACC check uses −1,000 bp the same way. A mild shock gives no warning; a shock reaching Y5 below growth still stops the run; the clean line and the warnings are stored in `notes`; a stored simulation with warnings still reproduces to the cent. Exit: green.

**Step 3. Report and command line.** `sim_report.render` gets a "## Warnings" section after the Summary, like the run report (`report.py`): every non-empty line of `notes` after the first (the band note, always first since M4), as bullets. When the only line after it is the clean line it says "None. No sample has a cost of equity at or below the risk-free rate or a discount rate at or below zero." When there is no line after the band note, the simulation was stored before this check, and it says "Not checked: this simulation was stored before Warren checked its rates. Run it again to check." `simulate` on the command line reads the notes back and prints each warning line after the result line, nothing when clean. Tests: the report shows each of the three cases; the command line prints a warning. Exit: green.

**Step 4. Docs.** Build Plan M4 "Result" notes the checks; after merge, v0.5.5 in `docs/versions.md`.

## What changes for stored results

No number changes and no stored simulation stops reproducing: `reproduce_simulation` compares shocks and bands, not notes, and the bands come from the same arithmetic. Simulations stored before this version say "Not checked" under Warnings.

## Alternatives considered

- *Stop the run, like the Y5 check.* Rejected. A low rate in one early period gives a value that exists, unlike Y5 at or below terminal growth, where the perpetuity does not converge. Stopping would also make any stored simulation with such samples fail `reproduce-sim` (it re-runs `simulate`), which relaxes an invariant; under CLAUDE.md that is the owner's call. The warning makes the problem visible with no such cost.
- *Drop the bad samples.* Rejected for the reason `_check_samples` gives: dropping samples biases the percentiles.
- *Only the WACC at or below zero, as the issue asked.* Rejected after review: it catches only gross typos. For an AAPL-like run (cost of equity about 10%), a −900 bp shock leaves WACC above zero, while the premium is long gone. The risk-free floor on the cost of equity has a source (CAPM); zero on WACC is kept as the plain second line.
- *A floor on WACC above zero (for example the risk-free rate).* Rejected: after-tax debt can rightly cost less than the risk-free rate, so a WACC below it is not wrong in itself.
- *A new column instead of notes lines.* Rejected: it needs a migration and its test for a sentence or two; `notes` is already where the run report reads warnings from.
- *Compute the warning when the report is rendered.* Rejected: it re-runs 10,000 samples to draw a page. Old simulations say "Not checked" instead.

## Files

`domains/analysis/dcf.py`, `domains/analysis/montecarlo.py`, `domains/analysis/sim_report.py`, `domains/analysis/__main__.py`, `tests/analysis/test_dcf.py`, `tests/analysis/test_montecarlo.py`, `docs/build-plan.md`, `docs/versions.md`.

## Design review

Explainer, analyst and professor, oct.31.2026, on the first draft. All three: no blockers (analyst GO, professor GO).

- **Analyst** (GO): zero on WACC catches only gross typos; the shock's own driver has a sourced floor, the risk-free rate under CAPM, and low-β companies (KO, JNJ, PG) and low-rate dates (2020) reach it long before zero. Taken: the negative-premium check. Taken: state the share and when it can set the p90 or p50, because low-rate samples sit in the upper tail of value; scan Y5 too; old simulations say "Not checked", not "None."; how the draw is shared is now spelled out. The Y5 check reading `discount_rates` was already done in Step 1.
- **Professor** (GO): the Problem paragraph mixed a negative premium with a rate below zero; now two separate items with sources (Sharpe 1964; Damodaran ch. 8). "No sourced line above zero" was too strong for the cost of equity; Alternatives corrected (still true for WACC). Taken: share in the wording; Y5 included. Student-environment idea (widen a shock until the warning fires) left for the lesson.
- **Explainer** (9 gaps, all answered in Step 2 and 3): the helper `_shocked` and `simulate_checked`; `rate_warnings` takes the shocked inputs; periods are the union, in period order; Y5 is now scanned; the test fixture and its two independent checks are stated; how the command line gets the warning and prints nothing when clean; the band note is the first line and blanks are dropped; old simulations say "Not checked". Not changed: a value-driver run with Y5 at or below zero already stops in `_check_samples` (Y5 at or below terminal growth) before the terminal value is computed, whenever g is above zero, as it is on every Phase 1 date; `FinancialMathError` is a `ValueError`, which the command line already reports.

## Review log

## Where the work stopped

- Steps 0–4 committed (531 tests green); PR and gatekeeper next.
