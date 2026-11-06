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
  1. *Each change's shape*, in the order the changes are given: for a terminal switch `_switch`'s own (`value_and_delta`, `period_on_single_value`, `unknown_terminal_method`, `same_terminal_method`); otherwise `use_on_other_input`, `debt_use_needed`, `debt_use_not_supported`, `method_on_number`, then `_targets` (`not_changeable`, `unknown_input`, `value_and_delta`, `period_on_single_value`, `unknown_period`) and `duplicate_change`. Unchanged.
  2. *The combination, and what the run must have for it*: `wacc_with_rate_input` (first name in `WACC_INPUTS` order, as now), then for a debt change `set_by_debt_change` (first name in `SET_BY_DEBT` order), `no_price` (the run has no price, so no buyback can be valued) and `cost_of_debt_needed` (new debt on a run that had none: the student must add an input). All three move out of `_leverage_rows` into `_refuse_debt_request`, with the same conditions.
  3. *The numbers*: `invalid_input` and `out_of_range` for each given change in order, then `buyback_exceeds_market_value`, then the bounds on the rows that follow (the revenue growth fade). The valuation's own refusals (`_value`: `growth_not_below_rate` and the other math reasons) and the source check come after all three stages.

  Implementation: the loop records each target with its change (shape checks as now) and computes `after` without the bound; the combination checks run on the keys; then the bounds run over the recorded rows in order. No refusal code or param changes; only which one wins when a request breaks two rules.
  Tests (`tests/analysis/test_whatif.py`): a buyback with `beta` changed and cash out of range gets `set_by_debt_change`; a set WACC with the cost of debt out of range gets `wacc_with_rate_input`; a buyback with `beta` changed and WACC set gets `wacc_with_rate_input` naming `beta` (combination order); a run with no price and a run with no debt refuse a buyback with cash out of range with `no_price` and `cost_of_debt_needed`; an unknown name after an out-of-range number gets the shape refusal; two numbers out of range give the first; a number out of range beats the buyback's size check; a debt change out of range alone still gets `out_of_range`; every existing refusal test still passes unchanged.
  Exit: tests pass.
- **Step 2. The held cost of debt is always said.** The guard becomes: the risk-free rate changed, the cost of debt did not (not set, added or floored), and `cost_of_debt_held_on_leverage` did not fire (debt did not rise, or the student set the cost). So debt down or unchanged with the risk-free rate moved now carries `cost_of_debt_held`, with its English text unchanged. One reason per case still holds (product lead, #170): when debt rises the leverage note says it and `cost_of_debt_held` stays off.
  The condition reads the changes, not the notes: risk-free in the changed names, cost of debt not (a floored row is a change), and not debt raised. Every case (analyst's matrix in the review): debt up and held, the leverage note only; debt up and floored or set, neither held note; debt down and floored, the floor note only; debt down and held, `cost_of_debt_held` (the fix); debt unchanged, `cost_of_debt_held`.
  Tests: debt −10 with risk_free +0.25 points carries `cost_of_debt_held` and not `cost_of_debt_held_on_leverage`; debt unchanged likewise, once; debt +10 with risk_free moved carries only the leverage note (as now); debt −10 floored carries neither held note; debt −10 with the cost of debt set carries neither.
  Exit: tests pass.
- **Step 3. A public row index in `dcf`.** `dcf._index` is renamed `dcf.index_rows` (same body, a docstring), and every caller, in `dcf`, `whatif`, `sources` and the tests, uses it. No alias is kept: nothing outside the repo imports Warren (the engine is a library for `webapp/`, which does not call it).
  Tests: the existing suite; a test that `index_rows` refuses two rows for one name and period (`DCFInputError`).
  Exit: tests pass, `grep "dcf\._index"` finds nothing.
- **Step 4. The CLI's `--debt-use` without debt is a usage error.** It is not an engine refusal (the CLI puts the use on the debt change only, so the engine's `use_on_other_input` can't be reached from the command line). `cmd_whatif` prints `usage error: --debt-use needs a --set or --add on debt` to standard error and returns 2, argparse's status for a usage mistake, with no `REFUSED (...)` code; it returns rather than calling `parser.error`, since the parser isn't in scope there and `main` returns the status. `--debt-use` with a debt change is unchanged.
  Tests (`tests/analysis/test_report_cli.py`): the existing case `--add beta=0.1 --debt-use buyback` (no debt change) changes as a spec change: it exited 1 with `REFUSED (use_on_other_input)` and now exits 2 with the usage line on standard error and no `REFUSED`.
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

Nothing added, renamed or removed in what the engine returns. Four behaviours change:

- When a what-if request breaks two rules, the refusal about what the request is (`wacc_with_rate_input`, `set_by_debt_change`) now comes before the one about a number (`out_of_range`, `invalid_input`). Same codes and params.
- A what-if with debt lowered (or unchanged) and the risk-free rate moved now carries `cost_of_debt_held`, an existing code already in the text catalogue.
- A simulation with zero samples on a child with WACC set and a risk-premium shock gets the coded refusal. No screen asks for zero samples.
- The command line's `--debt-use` with no debt change is a usage error (status 2), not `REFUSED (use_on_other_input)`. The app never builds that request.
- `dcf._index` is now `dcf.index_rows`; `webapp/` does not use it.

Questions served: brief Q7 and Q8 (what-if) read more consistently. No brief question changes status.

## Design review (nov.06.2026)

Explainer, analyst, professor and product lead in one fresh-context panel. NO-GO on the first draft with two blockers, both accepted:

- **`no_price` was in the wrong stage (analyst).** It is about the run, not a number: a buyback with cash out of range on a run with no price would refuse the number first, then the buyback. Moved to stage 2 with `cost_of_debt_needed` on a run that had no debt (the student must add an input), both in `_refuse_debt_request`; tests for each.
- **Step 4 claimed a test passes unchanged (explainer).** `test_report_cli.py`'s `--add beta=0.1 --debt-use buyback` goes through the CLI branch, not the engine, so it changes: written as a spec change, and how `cmd_whatif` returns the status is spelled out.

Taken from the gaps and ideas: `_switch`'s refusals are placed in stage 1; the guard is a condition on the changes with the analyst's case matrix written out; the valuation's own refusals are said to come after the three stages (professor); the combination test pins `name` beta (professor); the product impact lists every behaviour change, and the order change gets its own line in `docs/team-sync.md` at merge (product lead). Filed with #233 rather than here: with debt lowered to zero and the risk-free rate moved, `cost_of_debt_held` says "set cost_of_debt to move it too" about debt that no longer has any weight (also true today for a debt-free run).

## Results (Step 6, nov.06.2026)

On the snapshot of nov.05 (restored, no migration needed): `reproduce --all` 903 of 903 before the what-ifs. On each company's latest baseline (all as of 2026-10-30), a what-if with debt 10% lower (a buyback in reverse: shares issued to repay it) and the risk-free rate +25 bp:

- **Caterpillar**, the one company whose stored cost of debt is above the moved risk-free rate: the cost of debt is held and `cost_of_debt_held` is now said. Before this change, the what-if carried no note on it.
- **The other seven**: their book cost of debt is below the risk-free rate (as found in #170), so it is floored and `cost_of_debt_floored_at_risk_free` says so; no held note, as designed.
- All eight children reproduce; `reproduce --all` then 911 of 911. The children are on this machine's copy only and are not saved to the shared snapshot.

Full suite 1,495 passed, 10 skipped; ruff clean. No stored number changes.
