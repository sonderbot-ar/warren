# Backlog #234 and #229: leverage what-if tidy-ups and the order of refusals

Issues: https://github.com/sonderbot-ar/warren/issues/234 and https://github.com/sonderbot-ar/warren/issues/229 · Branch `backlog-234-leverage-tidy` · Version v0.9.28 when merged.

## Problem

Two gatekeeper reviews (PR #231, the leverage what-if; PR #228, a run with WACC set under a simulation) left small gaps. They are taken together because two of them are the same gap: when a request breaks two rules, which refusal the student sees is decided by the order the code happens to check things in, and no test fixes it.

1. **No note when debt falls and the risk-free rate moves** (#234.1). `whatif.revalue` adds `cost_of_debt_held` when the risk-free rate moves and the cost of debt does not, but skips it whenever debt changed, because `cost_of_debt_held_on_leverage` says it then. That note fires only when debt rises. So with debt down, the risk-free rate changed and no floor, nothing tells the student the cost of debt was held (`domains/analysis/whatif.py`, the guard above `cost_of_debt_held`).
2. **A private helper used from outside** (#234.2). `whatif.py` (three places) and `sources.py` call `dcf._index`, and three tests do too.
3. **Refusal order in the what-if** (#234.3). Bounds (`out_of_range`, `invalid_input`) are checked inside the loop over changes, before `wacc_with_rate_input` (after the loop) and `set_by_debt_change` (in `_leverage_rows`). A buyback with `beta` set to −5 gets `out_of_range` on beta; the student fixes the number and is then told beta can't be changed beside debt at all.
4. **The CLI's `--debt-use` without a debt change** (#234.4) prints `REFUSED (use_on_other_input)` with no input named, a code the engine never raises that way (`domains/analysis/__main__.py`, `cmd_whatif`).
5. **Refusal order in a simulation** (#229). `montecarlo._shocked` checks `n < 1` (uncoded text) before `_refuse_premium_on_set_wacc` (coded), so `n=0` with a risk-premium shock on a child with WACC set gets the uncoded error.

## Plan

- **Step 0.** This design doc. No build plan change (backlog items).
- **Step 1. One order for what-if refusals.** The rule, written in `_changed_rows`'s docstring: a refusal about what the request *is* comes before one about the *numbers* in it, so the first refusal a student sees is never one they can fix only to meet another. Three stages:
  1. *Each change's shape*, in the order the changes are given: `use_on_other_input`, `debt_use_needed`, `debt_use_not_supported`, `method_on_number`, then `_targets` (`not_changeable`, `unknown_input`, `value_and_delta`, `period_on_single_value`, `unknown_period`) and `duplicate_change`. Unchanged.
  2. *The combination*: `wacc_with_rate_input` (first name in `WACC_INPUTS` order, as now), then `set_by_debt_change` (moved out of `_leverage_rows` to here, first name in `SET_BY_DEBT` order).
  3. *The numbers*: `invalid_input` and `out_of_range` for each given change in order, then the leverage refusals that need the values (`no_price`, `buyback_exceeds_market_value`, `cost_of_debt_needed`), then the bounds on the rows that follow (the revenue growth fade).

  Implementation: the loop records each target with its change (shape checks as now) and computes `after` without the bound; the combination checks run on the keys; then the bounds run over the recorded rows in order. No refusal code or param changes; only which one wins when a request breaks two rules.
  Tests (`tests/analysis/test_whatif.py`): a buyback with `beta` set out of range gets `set_by_debt_change`; a set WACC with `risk_free` out of range gets `wacc_with_rate_input`; a buyback with `beta` changed and WACC set gets `wacc_with_rate_input` (combination order); a debt change out of range with no other change still gets `out_of_range`; an unknown name beside an out-of-range number gets the shape refusal; every existing refusal test still passes unchanged.
  Exit: tests pass.
- **Step 2. The held cost of debt is always said.** The guard becomes: the risk-free rate changed, the cost of debt did not (not set, added or floored), and `cost_of_debt_held_on_leverage` did not fire (debt did not rise, or the student set the cost). So debt down or unchanged with the risk-free rate moved now carries `cost_of_debt_held`, with its English text unchanged. One reason per case still holds (product lead, #170): when debt rises the leverage note says it and `cost_of_debt_held` stays off.
  Tests: debt −10 with risk_free +0.25 points carries `cost_of_debt_held` and not `cost_of_debt_held_on_leverage`; debt +10 with risk_free moved carries only the leverage note (as now); risk_free alone as now; a floored cost of debt carries neither `cost_of_debt_held` nor a duplicate.
  Exit: tests pass.
- **Step 3. A public row index in `dcf`.** `dcf._index` is renamed `dcf.index_rows` (same body, a docstring), and every caller, in `dcf`, `whatif`, `sources` and the tests, uses it. No alias is kept: nothing outside the repo imports Warren (the engine is a library for `webapp/`, which does not call it).
  Tests: the existing suite; a test that `index_rows` refuses two rows for one name and period (`DCFInputError`), which was untested under the old name.
  Exit: tests pass, `grep "dcf\._index"` finds nothing.
- **Step 4. The CLI's `--debt-use` without debt is a usage error.** It is not an engine refusal, so it is reported as argparse reports a bad flag: `parser.error("--debt-use needs a --set or --add on debt")`, exit status 2, no `REFUSED (...)` code. `--debt-use` with a debt change, and with `beta` (the engine's `use_on_other_input` with `name` beta, printed as now), are unchanged.
  Tests (`tests/analysis/test_report_cli.py`): `--debt-use` with no debt change exits 2 and prints no `REFUSED`; the existing `beta` case still prints `use_on_other_input`.
  Exit: tests pass.
- **Step 5. The coded simulation refusal first** (#229). In `montecarlo._shocked`, `_refuse_premium_on_set_wacc` runs before the sample count check, so a coded refusal always wins over the uncoded one. Reading the inputs (`dcf.inputs(rows)`) moves first too; it raises `DCFInputError` on broken rows, which no stored run has.
  Tests (`tests/analysis/test_montecarlo.py`): `n=0` with a risk-premium shock on a child with WACC set gets `wacc_set_with_risk_premium_shock`; `n=0` on a baseline still gets "need at least one sample".
  Exit: tests pass.
- **Step 6. Real data.** On the restored snapshot, `python -m domains.analysis reproduce --all` still passes, and on each company's latest baseline a what-if with debt −10% and risk-free +25 bp carries `cost_of_debt_held`. Results below. If the snapshot can't be restored, the step says so and the PR relies on the unit tests, since no stored row or number can change (nothing here changes a computation).
  Exit: every run reproduces.

**Exit criterion:** all tests pass, ruff is clean, no stored number changes.

**Point in time.** Nothing new is read.

**LLMs.** None.

## Alternatives considered

- **Pin today's order with tests and change nothing** (the other option #229 offers). Rejected for the what-if: today's order makes a student fix a number only to be told the change isn't allowed at all. Taken nowhere else: the simulation order is changed too, so the coded refusal always wins.
- **A new refusal code for `--debt-use` without debt.** Rejected: the app never builds that request (it sets `Change.use` on the debt change itself), so a code would add a catalogue entry no screen can reach. It is a command-line usage mistake and is reported as one.
- **Say "the cost of debt didn't fall" when debt falls.** Out of scope: #233 and #232 deal with how the cost of debt should follow leverage; this item only makes sure the hold is stated when the risk-free rate moves.
- **Keep `_index` as an alias.** Rejected: two names for one function, and nothing outside the repo depends on it.

## Files to change

`domains/analysis/whatif.py`, `domains/analysis/dcf.py`, `domains/analysis/sources.py`, `domains/analysis/montecarlo.py`, `domains/analysis/__main__.py`, tests in `tests/analysis/`. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Nothing added, renamed or removed in what the engine returns. Two behaviours change:

- When a what-if request breaks two rules, the refusal about what the request is (`wacc_with_rate_input`, `set_by_debt_change`) now comes before the one about a number (`out_of_range`, `invalid_input`). Same codes and params.
- A what-if with debt lowered (or unchanged) and the risk-free rate moved now carries `cost_of_debt_held`, an existing code already in the text catalogue.
- A simulation with zero samples on a child with WACC set and a risk-premium shock gets the coded refusal. No screen asks for zero samples.

Questions served: brief Q7 and Q8 (what-if) read more consistently. No brief question changes status.
