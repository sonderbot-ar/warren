# Backlog #212: a run with WACC set, under a simulation and in the grid

Issue: https://github.com/sonderbot-ar/warren/issues/212 · Branch `backlog-212-wacc-set-codes` · Version v0.9.26 when merged.

## Problem

v0.9.20 (backlog #171) lets a what-if child carry a `wacc` row: the student's discount rate replaces the one built from CAPM and the capital weights. Two places still speak as if no run could have one (both deferred from the #171 design review):

1. **A simulation on such a child with a risk-premium shock.** A risk-premium shock moves the cost of equity, which no longer enters the discount rate. `dcf.discount_rates` refuses the pair with a plain `DCFInputError` ("a WACC override and a cost-of-equity shift are different questions"); `montecarlo.save_simulation` lets it escape, and the CLI prints it as English text. The app needs a code and params to say why in Spanish. No student path simulates a child today (the pipeline and AI proposals take `parent_run_id IS NULL`), but the simulations list (v0.9.18) and the shocked range (v0.9.16) are built for any run id, so a screen can reach it.
2. **The sensitivity grid on such a child.** The grid's note `wacc_set_directly` (params `run_wacc`) says "in the company's own valuation it comes from CAPM and the capital weights". On a child with WACC set, the run's own rate is the student's, so the sentence is wrong for that run.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).
- **Step 1. The simulation refusal as a code.** `montecarlo.SimulationError` gains optional `code` and `params`, after the text: `SimulationError(text, code=None, params=None)` (so every existing `SimulationError(text)` is unchanged; the reverse of `GridError`'s order, explainer) and a `coded()` method like `GridError`'s. Before any sample is drawn (`montecarlo._shocked`), a run whose inputs carry `wacc_override` and any shock whose driver is `risk_premium` is refused with code `wacc_set_with_risk_premium_shock`, params `wacc` (the run's set rate) and `shock_ids` (the risk-premium shocks, in the order given). Nothing is stored. Other shocks on such a child still run and discount at the set rate, as v0.9.20 says. The new code goes in a new catalogue `coded.SIMULATION_REFUSAL_CODES` so the app's text catalogue can cover it; the constructor asserts any code it is given is in that set, and a test checks an uncatalogued code is refused. With WACC set, the samples' rate check (`rate_warnings`) skips the cost-of-equity line, which no longer values anything (analyst). `dcf.discount_rates` keeps its `DCFInputError` as the last guard for any other caller. The `simulate` CLI prints the code before the text.
  Tests (`tests/analysis/test_montecarlo.py`): a child with WACC set and a risk-premium shock is refused with the code and params, stores no simulation row; the same child with a revenue shock simulates, its baseline band equals the child's stored value per share, and its samples discount at the set rate; a baseline with a risk-premium shock is unchanged; the code is in the catalogue; a plain `SimulationError` has `code` None.
  Exit: tests pass.
- **Step 2. The grid's note on such a child.** `wacc_set_directly` gains a param `run_wacc_set` (`dcf.wacc_is_set(rows)`, the one test of a `wacc` row already used by `sources`; analyst, so the app picks the sentence from the params). With `true`, the English fallback says the run's own WACC was set directly too (a what-if), so neither it nor the grid's rows come from CAPM and the capital weights. Nothing else in the grid changes: its axes already centre on the run's rate (`dcf.base_wacc`, which returns the set rate).
  Tests (`tests/analysis/test_sensitivity.py`): on a baseline the note has `run_wacc_set` false and the old text; on a child with WACC set, true, the new text, and `run_wacc` equal to the set rate; the child's grid centre cell equals the child's stored value per share.
  Exit: tests pass.
- **Step 3. Real data.** On the restored snapshot: for each Phase 1 company's latest baseline, a what-if child with WACC +1 point; the grid on each child carries `run_wacc_set` true and its centre equals the child's value; a simulation with one risk-premium shock is refused with the code and stores nothing; a simulation with one revenue shock on the child runs and reproduces. `python -m domains.analysis reproduce --all` still passes. The children and simulations are made on this machine's copy and are not saved to the shared snapshot. Results below.
  Exit: every child and simulation reproduces; the refusal fires on every company.

**Exit criterion:** all tests pass, ruff is clean, and Step 3 holds on every company.

**Point in time.** Nothing new is read: the child's stored rows and the shocks given.

**LLMs.** None.

## Alternatives considered

- **Code the `DCFInputError` itself** (give every `DCFInputError` a code). Rejected: it is the dcf layer's guard for any caller, and the simulation is where a student meets it; refusing in `_shocked` also refuses before any sample is drawn.
- **Allow it and ignore the risk-premium shock.** Rejected: the student would see a band that left out the shock they asked for.
- **Re-express the risk-premium shock as a shift of the set WACC** (shift × the equity weight). This is the textbook pass-through of a cost-of-equity change to WACC (Koller, Goedhart and Wessels, *Valuation*, the WACC chapter; professor), and it is right for a run whose WACC is built from its parts. Rejected here as in #171: the student fixed the rate; moving it by an input they replaced answers a different question (design principle 4). Can be a later item if a screen asks for it.
- **A new grid note code instead of a param.** Rejected: the grid's notes are a fixed list keyed by code, and the issue offers either; a param keeps one code with one meaning (the grid sets WACC directly), and the app chooses the clause about the run's own rate.

## Files to change

`domains/analysis/montecarlo.py`, `domains/analysis/coded.py`, `domains/analysis/sensitivity.py`, `domains/analysis/dcf.py` (a docstring), `domains/analysis/__main__.py` (the CLI line), tests in `tests/analysis/`. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Nothing renamed or removed. Adds:

- `montecarlo.SimulationError` has `code`, `params` and `coded()`; `code` is None for every refusal that had no code before.
- Refusal code `wacc_set_with_risk_premium_shock` (params `wacc`, `shock_ids`: the ids as the user gave them, not the stored `<sim_id>:<shock_id>` form, since nothing is stored), listed in the new `coded.SIMULATION_REFUSAL_CODES`. Add it to the text catalogue.
- Grid note `wacc_set_directly` gains `run_wacc_set` (bool) on every grid, baseline or child. The app shows the "this run's own WACC was set too" clause when it is true.

Questions served: brief §2 (WACC set directly) together with Q7 and Q8 (a what-if, then the grid on it), and a future screen that simulates a what-if child. No brief question changes status.

## Design review (nov.06.2026)

Explainer, analyst, professor and product lead in one fresh-context panel. No blockers; GO on the design. Accepted:

- **Constructor order (explainer).** Written out in Step 1: text first, so old calls are unchanged.
- **How the catalogue is pinned (explainer).** The constructor asserts the code is catalogued; a test covers it.
- **Step 3 cleanup (explainer).** Children and simulations stay on this machine's copy.
- **The rate check on a child (analyst).** `rate_warnings` checked the CAPM cost of equity, which no longer enters the value, and would have advised "check the beta and the ERP"; with WACC set it now checks the discount rate only (test in `test_montecarlo.py`).
- **One test of "WACC is set" (analyst).** The grid uses `dcf.wacc_is_set(rows)`.
- **Name the textbook pass-through (professor).** Added to the alternatives.
- **Stale docstring (professor).** `dcf.base_wacc` now names the what-if's row.
- **Which shock ids (product lead).** Product impact says they are the ids as given.

Coverage checked by the analyst: every simulation path (`simulate_checked`, `sample_lines`, `simulate`, `save_simulation`, `reproduce_simulation`, and through them the harness, the pipeline and both range modules) goes through `montecarlo._shocked`, so the refusal covers them all; a shocked range needs a stored simulation, which a refusal never leaves. Kept, with a reason: the CLI line in `__main__.py` (the product lead suggested dropping it), because a plain `FAILED: …` hides the code the app keys on.

## Results on real data (Step 3, nov.06.2026)

On the restored snapshot (schema 21, saved nov.05.2026), on the latest stored baseline of each Phase 1 company (as of 2026-10-30), a what-if child with WACC +1 point:

- **The refusal fires on all eight.** A risk-premium shock (0 / 50 / 150 basis points) on each child is refused with `wacc_set_with_risk_premium_shock`, params the child's set rate and `["rp"]`; the simulations table has no new row after any of them.
- **Other shocks still run at the set rate.** A revenue-growth shock (−3 / −2 / −1 points for four quarters, 2,000 samples, seed 1) on each child stores a simulation that reproduces; its baseline band equals the child's value per share to the cent (AAPL $87.84, CAT $194.14, JNJ $144.62, KO $31.69, MSFT $183.79, PG $90.48, WMT $26.88, XOM $99.64, the same values v0.9.20 recorded for +1 point), and the p50 sits 1.5–2.3% below it (AAPL $86.10, MSFT $180.40, XOM $97.31).
- **The grid's note.** On every child `wacc_set_directly` has `run_wacc_set` true and `run_wacc` the set rate (AAPL 12.15%, XOM 7.50%); on every parent it is false. Each child's grid centre equals its stored value per share exactly.
- `python -m domains.analysis reproduce --all`: 911 of 911 runs reproduce to the cent (903 stored runs and the 8 children made here). Full suite: 1,446 passed, 10 skipped. Each call takes under 0.1 s. Nothing here is saved to the shared snapshot.

## Merged

nov.06.2026 as v0.9.26, PR #228, merge `5d43647`, after CI and the gatekeeper's GO (no blockers; all 124 stored simulations reproduce). The gatekeeper's idea on the refusal order with `n=0` is #229.
