# Backlog #79: the value-driver terminal value refuses growth at or above WACC

Issue: https://github.com/sonderbot-ar/warren/issues/79 · Branch `backlog-79-growth-below-wacc` · Version v0.5.4 when merged.
Owner decision (oct.31.2026, decision card): "Refuse it, like the old rule."

## Problem

Since M4 the terminal value is NOPAT_Y5 × (1 + g) / WACC (Decision 4, value-driver form with RONIC = WACC). That closed form is a growing perpetuity, FCF / (WACC − g) with FCF = NOPAT × (1 + g) × (1 − g / WACC), where the (WACC − g) terms cancel. The perpetuity only converges when g < WACC (Koller, Goedhart and Wessels, *Valuation*, 7th ed., ch. 14). At g = WACC the cash flow is zero forever; at g > WACC the sum diverges. The code refuses only WACC ≤ 0 (`financial_math.value_driver_terminal_value`), so at 0 < WACC ≤ g it returns a value that does not exist:

- at ERP − 1 SE in a baseline run, where under Gordon the same inputs gave no value for 6 of 40 M2.1 runs (Build Plan M2.1 Result);
- in the Monte Carlo, whose sample check uses a floor of 0 under the value-driver rule (`montecarlo._check_samples`).

Decision 4 already says "terminal growth must be below WACC" fails loudly.

## Plan

**Step 0. This design doc; the owner decision recorded in the Structure Guide** (Decision 4 additions and its log row). Exit: docs on the branch.

**Step 1. The formula refuses g ≥ WACC.** `value_driver_terminal_value` raises `FinancialMathError(..., "growth_not_below_rate")` when g ≥ WACC (checked after WACC ≤ 0, which keeps `rate_not_positive`). Like the other checks it uses `_any`, so an array of samples is refused if any sample fails. The baseline then stores a gap for ERP ± 1 SE with that reason (v0.5.2's machinery) and the report says "WACC ≤ terminal growth".
Tests: g = WACC and g > WACC are refused with `growth_not_below_rate`; WACC ≤ 0 still gives `rate_not_positive`; g just below WACC gives NOPAT × (1 + g) / WACC by hand; `outputs_and_gaps` under the value-driver rule with ERP − 1 SE at WACC = g stores the gap. The v0.5.2 test that pinned a value at g > WACC (`test_the_value_driver_form_has_a_value_below_growth`) asserted the defect and is replaced by the refusal test. Exit: `pytest`, `ruff check`, `ruff format --check` green.

**Step 2. The Monte Carlo floor is terminal growth for both rules.** `_check_samples` refuses samples whose Y5 discount rate is at or below terminal growth, whatever the terminal rule, with the same count message. Tests: a value-driver simulation whose samples push Y5 WACC to g stops with the count; one that stays above runs as before. Exit: green.

**Step 3. Docs.** Build Plan M4 Result notes (the terminal value now needs g < WACC); after merge, v0.5.4 in `docs/versions.md`.

## What changes for stored results

No base valuation is expected to change: every base run in the M2.1 grid had WACC above g (Gordon, which refuses g ≥ WACC, gave all 40 a value), and a base run at g ≥ WACC would now stop with an error instead of storing a value. A value-driver run that stored an ERP − 1 SE value at WACC ≤ g will now show a mismatch in `reproduce` for that one output (stored a value, now none). That is the intended effect: the stored number did not exist. Such runs should be valued again. A stored simulation whose samples reach WACC ≤ g will no longer reproduce; it stops instead. The cloud environment has no database, so the count of affected runs is checked on the owner's database after merge (`python -m domains.analysis reproduce --all`); the desk entry says so.

## Alternatives considered

- *Keep the value and warn.* Rejected by the owner: the number does not exist.
- *A new terminal method name, so old runs keep reproducing with the old behaviour.* Rejected: it would preserve a known-wrong number as a supported rule.
- *Clip g to just below WACC.* Rejected: it invents a value from an arbitrary margin, and the value at g → WACC from below is NOPAT × (1 + g) / WACC, finite, so clipping hides that the sum never converges at g ≥ WACC.

## Files

`domains/analysis/financial_math.py`, `domains/analysis/montecarlo.py`, `tests/analysis/test_financial_math.py`, `tests/analysis/test_dcf.py`, `tests/analysis/test_montecarlo.py`, `docs/structure-guide.md`, `docs/build-plan.md`, `docs/versions.md`.

## Review log

The decision was the owner's, so the design went straight to build; the analyst and gatekeeper reviewed the PR together.

- **Analyst** (GO, no blockers): the fix is how a practitioner computes it; at g = WACC all NOPAT is reinvested and FCF is zero forever, at g > WACC the sum diverges (Koller, Goedhart and Wessels, ch. 14). The order of checks is sensible, and the Monte Carlo floor uses Y5's rate, the one the terminal value uses. Taken: a property test tying the closed form to the perpetuity it comes from. To backlog: a risk-premium shock that ends before Y5 can push an earlier period's WACC to zero or below unreported (a valid discount, not a missing value). For the desk: say that a reproduce check on the owner's database may show mismatches for ERP − 1 SE and for simulations, by design.
- **Gatekeeper** (GO, no blockers; 521 tests, ruff clean, CI green): the replaced test asserted the defect the owner ruled out, and its replacements check more. Taken: a property test that both terminal rules refuse g ≥ WACC. To do after merge: count affected runs on the owner's database.

## Where the work stopped

- Steps 0–3 built and reviewed (GO from analyst and gatekeeper), PR #89. Next: merge, v0.5.4.
