# Backlog #171: WACC set directly on a what-if

Issue: https://github.com/sonderbot-ar/warren/issues/171 · Branch `backlog-171-wacc-set` · Version v0.9.20 when merged.

## Problem

Brief §2 (`docs/product/brief.md`) lists "WACC set directly" among the inputs a student may change. The what-if (v0.9.9, `domains/analysis/whatif.py`) refuses it: WACC is an output of `dcf.base_wacc`, computed from CAPM and the debt rows, so there is no row to change. A student who asks "what is Walmart worth at a 9% discount rate?" today has to reverse-engineer a beta that gives 9%, which teaches the wrong thing. The sensitivity grid (v0.9.12) already sets WACC directly, but only in memory (`dcf.Inputs.wacc_override`) and never stored.

The issue's second half, letting a student switch the terminal method on a what-if, touches the owner's choice under Decision 4. It went to the owner as a decision card (nov.05.2026) and is not built here; if the owner says yes, it is its own item on top of this one.

## What changes

1. **An optional run row `wacc`** (period `-`, source `user`). `dcf.inputs` reads it into `Inputs.wacc_override` when present; a run without it is valued exactly as before, so every stored run still reproduces. Only a what-if child gets it: `math_engine` never writes one, so no baseline has it (nothing else refuses it on a baseline; it would simply be valued). With a cost-of-equity shift (the Monte Carlo sets one later through `replace`), `dcf.discount_rates` refuses it, as it already does for the in-memory override.
2. **What it replaces.** The set WACC is the discount rate in every period and the roll-forward rate, as in the grid. The cost of equity is still CAPM on the stored rows and is shown, unchanged, for reference; the weights, the cost of debt and the cash flows stay as stored. Terminal growth does not move.
3. **The what-if takes `wacc`**: `Change("wacc", value=0.09)` sets it, `Change("wacc", delta=0.01)` adds to the parent's stored WACC (its `wacc` output). It must be above zero (`out_of_range`), and `financial_math` already refuses a WACC at or below terminal growth (`growth_not_below_rate`). It is refused together with any input the computed WACC is built from (`risk_free`, `beta`, `erp`, `cost_of_debt`, `debt_tax_rate`): with WACC set those would move nothing but the cost-of-equity line, and a student would read that as a result (`wacc_with_rate_input`, params `name`). Terminal growth may be changed beside it.
4. **ERP ± 1 SE is not computed when WACC is set.** The run's ERP no longer enters the discount rate, so value per share at ERP ± 1 SE would equal the point and look like precision. The child stores neither bound and no gap. Instead the child's stored run notes carry a post-check `erp_bounds_not_computed` (a run note code, so any later read of the child, not only the what-if's answer, can say why; product lead), the what-if shows it as a `run_warning`, and the report's sensitivity line says "not computed: WACC set directly". The ERP-bound spread warning is skipped for the same reason.
4a. **An override, not a weighted average (analyst, professor; must-fix).** A WACC is a weighted average, so it lies between debt's after-tax cost and the cost of equity. A set WACC need not: MSFT_2026-10-30_1 has WACC 11.45% and cost of equity 11.70%, so +1 point shows a WACC above the cost of equity beside it. The child keeps the cost-of-equity line (CAPM on its rows, for reference) and adds a stored post-check `wacc_outside_its_parts` (params `wacc`, `cost_of_equity`, `after_tax_cost_of_debt`, the last from a new `financial_math.after_tax_cost_of_debt`, which `fm.wacc` now uses) when the set rate is outside that interval; the what-if's note says it is an override.
5. **Sources and trace.** The new row gets a `what_if` source with `before` (the parent's WACC output) and empty `parent_sources`; `sources.for_child` adds sources for rows the parent did not have. In the output trace, the `wacc` output's formula is `wacc_as_set` (in `sources.FORMULAS`), from the row alone; the ERP ± 1 SE outputs are left out of the trace when WACC is set.
6. **Lines and notes.** `driven_by` adds `wacc` to every line computed from the discount rate (WACC, discount factors, present values, terminal value, enterprise and equity value, value per share), not to the cost of equity. A new what-if note `wacc_set_on_what_if` (params `before`, `after`; not the grid's `wacc_set_directly`, whose params differ, product lead) says it is an override and the cost of equity, beta, ERP and the debt weights no longer drive the rate. On a value-driver run (every run since M4) the what-if adds `ronic_follows_wacc` (the grid's code and params): new investment's return after year 5 moves with the set WACC (analyst). A refusal `growth_not_below_rate` now carries `wacc` and `terminal_growth` as params (analyst: XOM, JNJ and KO are refused about 1.5–1.9 points below their WACC, at growth 4.98%).

**Point in time.** Nothing is read but the parent's stored rows and outputs, which were point in time on its date.

**LLMs.** None. The student names the rate; `financial_math` does every number.

**Downstream.** A Monte Carlo on a child with WACC set and a risk-premium shock is refused (`DCFInputError`, "a WACC override and a cost-of-equity shift are different questions"); other shocks discount at the set WACC. The sensitivity grid on such a child replaces the set WACC with each axis value, as it does for any run.

## Steps

- **Step 0.** This design doc; no build plan change (a backlog item).
- **Step 1.** `dcf.inputs` reads the optional `wacc` row; `dcf.outputs_and_gaps` skips the ERP bounds when it is set; `math_engine.post_check_notes` skips the ERP-bound spread check; `sources.output_trace` gives `wacc_set_directly` and drops the ERP-bound outputs; `report` says "not computed". Tests (`tests/analysis/test_dcf.py`, `test_sources.py`): a run with a `wacc` row values exactly as `Inputs.wacc_override` does and as the grid's cell at that WACC; rows without it give byte-identical outputs to today; no ERP-bound outputs or gaps with it; the output-trace test (each moved row changes exactly the outputs its trace reaches) passes on rows with a `wacc` row under both terminal methods; a `wacc` row with a cost-of-equity shift is refused. Exit: green.
- **Step 2.** `whatif` takes `wacc`: bounds, the refusal beside a rate input, `delta` from the parent's WACC output, the new row in the child with its source, `driven_by`, the notes; the CLI accepts `--set wacc=0.09`. Tests (`tests/analysis/test_whatif.py`, `test_report_cli.py`, `test_post_check_codes.py`, `test_financial_math.py`): set and add give the same values (two children: their method texts differ, as for any input; explainer); the child reproduces with `runs.reproduce`; its rows equal the parent's plus one `wacc` row; value per share equals `dcf.compute` with `wacc_override`; cost of equity unchanged and not in `driven_by`; refused beside each of the five rate inputs, at 0, below zero, at terminal growth, each storing nothing; terminal growth set beside it works; a second identical call is `reused`; `src.check` passes on the child; the CLI prints the table. Exit: green, ruff clean.
- **Step 3.** Real data on the restored snapshot: on the latest stored run of each Phase 1 company, WACC set to the parent's own WACC gives the parent's value per share to the cent (a property: setting the rate to what it was changes nothing but the ERP bounds); then Walmart at 9% and Microsoft at +1 point; every child reproduces; `reproduce --all` still passes. Results below. Exit: every child reproduces; the numbers are written here.

**Exit criterion:** all tests pass; Step 3's children reproduce to the cent and the identity check holds on every company.

## Alternatives considered

- **Shift the set WACC by the ERP's weight for the ERP ± 1 SE bounds** (w_E × β × SE). Rejected: the student fixed the rate, so a band from an input they replaced answers a different question; showing it would blur "my assumption" and "the model's uncertainty" (design principle 4).
- **Store the set WACC on the cost of equity instead** (back out a cost of equity that gives it). Rejected: it invents a cost of equity the student did not name and breaks the CAPM line.
- **Allow rate inputs beside it and note that they do nothing.** Rejected: refusing is clearer than a moved input with no effect.
- **Build the terminal-method switch now.** Rejected: it touches the owner's choice (Decision 4); it waits for the owner's card.

## Files to change

Changed: `domains/analysis/dcf.py`, `domains/analysis/math_engine.py` (one guard), `domains/analysis/sources.py`, `domains/analysis/report.py`, `domains/analysis/whatif.py`, `domains/analysis/__main__.py` (only if the CLI needs it), tests in `tests/analysis/`. At merge: `docs/versions.md`, `docs/team-sync.md`, `docs/product/brief.md` (§2's input list).

## Product impact

Serves brief §2's "WACC set directly" input (the what-if behind questions 7 and 8). Adds, with nothing renamed or removed:

- `Change("wacc", value=…)` or `delta=…`; a change row `name` `wacc`, `before` the parent's WACC.
- Refusal code `wacc_with_rate_input` (params `name`); `out_of_range` for `wacc` (`low` 0); `growth_not_below_rate` now has params `wacc` and `terminal_growth`.
- What-if note codes `wacc_set_on_what_if` (params `before`, `after`) and, on value-driver runs, `ronic_follows_wacc` (params `terminal_method`, as the grid's).
- Two new run note codes in `RUN_NOTE_CODES`, stored on the child and shown by the what-if as `run_warning`: `erp_bounds_not_computed` (no params) and `wacc_outside_its_parts` (params `wacc`, `cost_of_equity`, `after_tax_cost_of_debt`). Add both to the text catalogue.
- A child with WACC set has no `value_per_share_erp_minus_1se` / `_plus_1se` output and no gap for them; the app shows "not computed" from `erp_bounds_not_computed`, never "no value".
- `run_sources`: the `wacc` row's source is `what_if`; the `wacc` output's formula is `wacc_as_set`.
- Brief §2's "WACC set directly" input; Q7 and Q8 do not set WACC, so their status is unchanged (professor).

The terminal-method switch (the rest of #171) waits for the owner's card.

## Design review (nov.05.2026)

Explainer, analyst, professor and product lead in one fresh-context panel. Accepted:

- **A set WACC outside its own parts (analyst, professor; must-fix).** MSFT_2026-10-30_1: WACC 11.45%, cost of equity 11.70%; +1 point shows a WACC above the cost of equity beside it, which no weighting gives. Item 4a: a stored post-check `wacc_outside_its_parts` with the three rates, and the what-if note says "an override, not a weighted average".
- **Code collision (product lead; must-fix).** `wacc_set_directly` is the grid's note with other params; the what-if note is now `wacc_set_on_what_if` and the trace formula `wacc_as_set`.
- **"Same child" (explainer, analyst; must-fix).** Set and add store two children (their method text differs); the step now says same values.
- **The reason for missing bounds is stored (product lead).** `erp_bounds_not_computed` is a run note, so the report and any later read can say why.
- **RONIC follows WACC and refusal params (analyst).** `ronic_follows_wacc` on value-driver runs; `growth_not_below_rate` carries both rates.
- **Explainer gaps** answered in items 1, 3 and 4 (how `before` is found, where the shift is refused, what keeps the row off baselines).

Rejected or deferred, with the reason:

- **A code for the Monte Carlo refusal (product lead).** No student path runs a simulation on a what-if child: the pipeline and the AI proposals use baselines only (`parent_run_id IS NULL`, v0.9.9), and the refusal is the existing `DCFInputError` for the grid's override. Filed as a backlog issue for when simulations on children become a screen.
- **The grid's note on such a child (analyst, idea).** On a child with WACC set, the grid's `wacc_set_directly` text says the run's WACC "comes from CAPM"; filed as a backlog issue (a param or a variant of the note).
- **Reports for children.** A report is written only for a baseline (`__main__.py`); `report.render` works on a child and says "not computed"; nothing else changes.

## Results on real data (Step 3, nov.05.2026)

On the restored snapshot (schema 21), on the latest stored run of each company (as of 2026-10-30):

- **Identity on all eight companies.** WACC set to the run's own WACC gives the run's value per share exactly (change 0.0, not just to the cent) on AAPL, CAT, JNJ, KO, MSFT, PG, WMT and XOM.
- **+1 point on each** (value per share before → after): AAPL $95.21 → $87.84 (−7.7%), CAT $218.45 → $194.14 (−11.1%), JNJ $168.01 → $144.62 (−13.9%), KO $37.37 → $31.69 (−15.2%), MSFT $203.55 → $183.79 (−9.7%), PG $104.13 → $90.48 (−13.1%), WMT $31.24 → $26.88 (−14.0%), XOM $116.23 → $99.64 (−14.3%). Every one of these is flagged `wacc_outside_its_parts`: on every company the cost of equity is less than a point above WACC (AAPL 11.30% vs 11.15%, CAT 11.62% vs 10.79%), so +1 point is a rate no mix of this run's debt and equity could give. That is what the analyst's must-fix was about, and the note fires as designed.
- **WACC 9%:** Walmart (8.87% computed, cost of equity 9.18%) $31.24 → $30.64 (−1.9%), inside its parts, no warning; Microsoft (11.45%) $203.55 → $271.59 (+33.4%), also inside its parts (between debt's after-tax cost and the cost of equity), so neither gets the warning; the only stored note on both is `erp_bounds_not_computed`.
- **WACC 4.5% on XOM, JNJ and KO** is refused, `growth_not_below_rate` with `wacc` 0.045 and `terminal_growth` 0.0498.
- Each call takes 0.01–0.03 s; every child reproduces. `python -m domains.analysis reproduce --all`: 921 of 921 runs reproduce to the cent (903 stored runs and the 18 children made here). The children were made on this machine's copy and are not saved to the shared snapshot.
