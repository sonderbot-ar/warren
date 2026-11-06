# Backlog #238: one "would be floored" check, two named reasons a cost of debt is needed, a NaN pin

Issue: https://github.com/sonderbot-ar/warren/issues/238 · Branch `backlog-238-floor-check` · Version v0.9.29 when merged.

## Problem

The gatekeeper's review of PR #237 (v0.9.28) found three places where the leverage what-if is right today but could drift:

1. **One condition, written as one disjunction** (`domains/analysis/whatif.py`, `_refuse_debt_request`): `d_after > 0 and ((held and d_before == 0) or (kd == 0 and not (held and d_before != 0)))`. It holds two reasons a student must give a cost of debt, and neither is named or pinned on its own. The English text also says "the run had no debt" when the run had debt and the rate is zero.
2. **"Would be floored" written twice.** `_refuse_debt_request` (as `held`) and `_leverage_rows` (the floored row) each compute "cost of debt not given, debt moved, the run's rate below the child's risk-free rate". If one is edited and not the other, the refusal and the floor disagree.
3. **No test for a NaN risk-free rate** beside new debt on a debt-free run: stage 2's `cost_of_debt_needed` wins over stage 3's `invalid_input`, as the v0.9.28 order says, but nothing fixes it.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. One check, named reasons.** A new `_would_floor(index, out)`: the cost of debt was not given, debt moved and is above zero, and the run's cost of debt is below the child's risk-free rate (the student's or the run's). `_refuse_debt_request` calls it once and returns its answer; `_changed_rows` passes it to `_leverage_rows`, which writes the floored row only when it is true. `held` gained `d_after > 0`, which the old refusal already required around it and the old floor checked separately, so no request changes outcome.
  The refusal becomes two named predicates under `d_after > 0`: `new_debt_without_a_rate` (a debt-free run, the stored 0 is a placeholder, and the floor would otherwise turn it into the risk-free rate) and `zero_rate_not_floored` (a zero rate on debt above zero, unless the floor replaces it on a run that had debt). Same code (`cost_of_debt_needed`), same params (`debt_before`). The English fallback text says "the run had no debt, so it has no cost of debt: set cost_of_debt above 0" when it had none (it said "set cost_of_debt too", which reads oddly when the student already gave 0), and "a cost of debt of 0 would make the debt free: set cost_of_debt above 0" when it had some.
  Tests (`tests/analysis/test_whatif.py`): `_would_floor` against five requests (debt up or down past the floor, a rate above the risk-free, debt unchanged, a rate given), each checked against the row the child actually stores; debt cut to zero is never floored; unchanged debt with the cost of debt set to 0 is refused with the new text and stores nothing; a run with debt and a zero book rate is floored, not refused, when debt moves, and reproduces; the same run with debt unchanged is refused; new debt on a debt-free run with a zero rate given is refused with the "had no debt" text; new debt on a debt-free run whose stored rate is not 0 but below the risk-free rate is refused (the only test that reaches `new_debt_without_a_rate` alone), and with the rate above risk-free it is held; a negative risk-free rate floors nothing, so a zero rate on a run with debt is refused. Each predicate replaced by a constant fails a test (checked by hand).
  Exit: tests pass, every existing test unchanged.
- **Step 2. The NaN pin.** Test: a NaN risk-free rate beside new debt on a debt-free run gets `cost_of_debt_needed` and stores nothing; with a cost of debt given too, the NaN gets `invalid_input` naming `risk_free`.
  Exit: tests pass.

**Exit criterion:** all tests pass, ruff clean, no request changes outcome and no stored number changes (only one English fallback sentence). No real-data step: nothing here reads data or changes a computation, and v0.9.28's 911-of-911 reproduce stands.

**Point in time.** Nothing new is read. **LLMs.** None.

## Alternatives considered

- **Keep the disjunction and add comments.** Rejected: the issue's point is that tests pin each branch, which needs names to point at.
- **A new code for the zero-rate case** (`cost_of_debt_zero`). Rejected: the student's fix is the same (give a cost of debt above zero), so one code with the right sentence serves the app; a new code would add a catalogue entry for the front-end team for no new action.
- **Let `_leverage_rows` compute the floor and the refusal read its rows.** Rejected: the refusal must come in stage 2, before the numbers are checked, and `_leverage_rows` runs in stage 3 and can itself refuse (`buyback_exceeds_market_value`).

## Files to change

`domains/analysis/whatif.py`, `tests/analysis/test_whatif.py`. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

No code, param or output added, renamed or removed. Two English fallback texts change (the code and params do not): `cost_of_debt_needed` on a run that had debt (a cost of debt of 0 given with debt above zero) now says the zero rate would make the debt free, instead of saying the run had no debt; on a debt-free run it now ends "set cost_of_debt above 0" instead of "set cost_of_debt too". The app's own sentence for `cost_of_debt_needed` should not assume the run had no debt; `params.debt_before` tells the two apart (0 or not). Brief questions served: Q7 and Q8 (what-if), unchanged in status.

## Design review (nov.06.2026)

Explainer, analyst and professor in one fresh-context panel. Explainer: clear, steps match the diff. Analyst: no request changes outcome (refusal, floor, NaN, debt cut to zero or below, a given rate or risk-free rate, each compared with `main`). Professor: the floor and the zero-rate refusal are defensible and easier to teach with names.

- **Blocker, accepted:** no test reached `new_debt_without_a_rate` alone, since every debt-free test also had a stored rate of 0, so the zero-rate reason refused anyway. Added a test with only debt zeroed (book rate 4%, risk-free 5%); replacing the predicate with `False` now fails it.
- **Taken:** the debt-free text now ends "set cost_of_debt above 0"; a test for a negative risk-free rate on a run with debt and a zero rate; the `debt_before` note goes to `docs/team-sync.md` at merge.
