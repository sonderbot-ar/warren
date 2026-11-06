# Backlog #212: a run with WACC set, under a simulation and in the grid

Issue: https://github.com/sonderbot-ar/warren/issues/212 · Branch `backlog-212-wacc-set-codes` · Version v0.9.26 when merged.

## Problem

v0.9.20 (backlog #171) lets a what-if child carry a `wacc` row: the student's discount rate replaces the one built from CAPM and the capital weights. Two places still speak as if no run could have one (both deferred from the #171 design review):

1. **A simulation on such a child with a risk-premium shock.** A risk-premium shock moves the cost of equity, which no longer enters the discount rate. `dcf.discount_rates` refuses the pair with a plain `DCFInputError` ("a WACC override and a cost-of-equity shift are different questions"); `montecarlo.save_simulation` lets it escape, and the CLI prints it as English text. The app needs a code and params to say why in Spanish. No student path simulates a child today (the pipeline and AI proposals take `parent_run_id IS NULL`), but the simulations list (v0.9.18) and the shocked range (v0.9.16) are built for any run id, so a screen can reach it.
2. **The sensitivity grid on such a child.** The grid's note `wacc_set_directly` (params `run_wacc`) says "in the company's own valuation it comes from CAPM and the capital weights". On a child with WACC set, the run's own rate is the student's, so the sentence is wrong for that run.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).
- **Step 1. The simulation refusal as a code.** `montecarlo.SimulationError` gains optional `code` and `params` (both default to `None` and `{}`, so every existing `SimulationError(text)` is unchanged) and a `coded()` method like `GridError`'s. Before any sample is drawn (`montecarlo._shocked`), a run whose inputs carry `wacc_override` and any shock whose driver is `risk_premium` is refused with code `wacc_set_with_risk_premium_shock`, params `wacc` (the run's set rate) and `shock_ids` (the risk-premium shocks, in the order given). Nothing is stored. Other shocks on such a child still run and discount at the set rate, as v0.9.20 says. The new code goes in a new catalogue `coded.SIMULATION_REFUSAL_CODES` so the app's text catalogue can cover it; a test pins that every coded `SimulationError` raised uses a code from it. `dcf.discount_rates` keeps its `DCFInputError` as the last guard for any other caller. The `simulate` CLI prints the code before the text.
  Tests (`tests/analysis/test_montecarlo.py`): a child with WACC set and a risk-premium shock is refused with the code and params, stores no simulation row; the same child with a revenue shock simulates, its baseline band equals the child's stored value per share, and its samples discount at the set rate; a baseline with a risk-premium shock is unchanged; the code is in the catalogue; a plain `SimulationError` has `code` None.
  Exit: tests pass.
- **Step 2. The grid's note on such a child.** `wacc_set_directly` gains a param `run_wacc_set` (`true` when the run has a `wacc` row, else `false`, so the app picks the sentence from the params). With `true`, the English fallback says the run's own WACC was set directly too (a what-if), so neither it nor the grid's rows come from CAPM and the capital weights. Nothing else in the grid changes: its axes already centre on the run's rate (`dcf.base_wacc`, which returns the set rate).
  Tests (`tests/analysis/test_sensitivity.py`): on a baseline the note has `run_wacc_set` false and the old text; on a child with WACC set, true, the new text, and `run_wacc` equal to the set rate; the child's grid centre cell equals the child's stored value per share.
  Exit: tests pass.
- **Step 3. Real data.** On the restored snapshot: for each Phase 1 company's latest baseline, a what-if child with WACC +1 point; the grid on each child carries `run_wacc_set` true and its centre equals the child's value; a simulation with one risk-premium shock is refused with the code and stores nothing; a simulation with one revenue shock on the child runs and reproduces. `python -m domains.analysis reproduce --all` still passes. Results below.
  Exit: every child and simulation reproduces; the refusal fires on every company.

**Exit criterion:** all tests pass, ruff is clean, and Step 3 holds on every company.

**Point in time.** Nothing new is read: the child's stored rows and the shocks given.

**LLMs.** None.

## Alternatives considered

- **Code the `DCFInputError` itself** (give every `DCFInputError` a code). Rejected: it is the dcf layer's guard for any caller, and the simulation is where a student meets it; refusing in `_shocked` also refuses before any sample is drawn.
- **Allow it and ignore the risk-premium shock.** Rejected: the student would see a band that left out the shock they asked for.
- **Re-express the risk-premium shock as a shift of the set WACC** (shift × the equity weight). Rejected as in #171: the student fixed the rate; moving it by an input they replaced answers a different question (design principle 4). Can be a later item if a screen asks for it.
- **A new grid note code instead of a param.** Rejected: the grid's notes are a fixed list keyed by code, and the issue offers either; a param keeps one code with one meaning (the grid sets WACC directly), and the app chooses the clause about the run's own rate.

## Files to change

`domains/analysis/montecarlo.py`, `domains/analysis/coded.py`, `domains/analysis/sensitivity.py`, `domains/analysis/__main__.py` (the CLI line), tests in `tests/analysis/`. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Nothing renamed or removed. Adds:

- `montecarlo.SimulationError` has `code`, `params` and `coded()`; `code` is None for every refusal that had no code before.
- Refusal code `wacc_set_with_risk_premium_shock` (params `wacc`, `shock_ids`), listed in the new `coded.SIMULATION_REFUSAL_CODES`. Add it to the text catalogue.
- Grid note `wacc_set_directly` gains `run_wacc_set` (bool) on every grid, baseline or child. The app shows the "this run's own WACC was set too" clause when it is true.

Questions served: brief §2 (WACC set directly) together with Q7 and Q8 (a what-if, then the grid on it), and a future screen that simulates a what-if child. No brief question changes status.
