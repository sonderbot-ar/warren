# Backlog #171: WACC set directly on a what-if

Issue: https://github.com/sonderbot-ar/warren/issues/171 · Branch `backlog-171-wacc-set` · Version v0.9.20 when merged.

## Problem

Brief §2 (`docs/product/brief.md`) lists "WACC set directly" among the inputs a student may change. The what-if (v0.9.9, `domains/analysis/whatif.py`) refuses it: WACC is an output of `dcf.base_wacc`, computed from CAPM and the debt rows, so there is no row to change. A student who asks "what is Walmart worth at a 9% discount rate?" today has to reverse-engineer a beta that gives 9%, which teaches the wrong thing. The sensitivity grid (v0.9.12) already sets WACC directly, but only in memory (`dcf.Inputs.wacc_override`) and never stored.

The issue's second half, letting a student switch the terminal method on a what-if, touches the owner's choice under Decision 4. It went to the owner as a decision card (nov.05.2026) and is not built here; if the owner says yes, it is its own item on top of this one.

## What changes

1. **An optional run row `wacc`** (period `-`, source `user`). `dcf.inputs` reads it into `Inputs.wacc_override` when present; a run without it is valued exactly as before, so every stored run still reproduces. Only a what-if child can have it: `math_engine` never writes it, and `dcf.inputs` refuses it together with a cost-of-equity shift (as `discount_rates` already does).
2. **What it replaces.** The set WACC is the discount rate in every period and the roll-forward rate, as in the grid. The cost of equity is still CAPM on the stored rows and is shown, unchanged, for reference; the weights, the cost of debt and the cash flows stay as stored. Terminal growth does not move.
3. **The what-if takes `wacc`**: `Change("wacc", value=0.09)` sets it, `Change("wacc", delta=0.01)` adds to the parent's stored WACC (its `wacc` output). It must be above zero (`out_of_range`), and `financial_math` already refuses a WACC at or below terminal growth (`growth_not_below_rate`). It is refused together with any input the computed WACC is built from (`risk_free`, `beta`, `erp`, `cost_of_debt`, `debt_tax_rate`): with WACC set those would move nothing but the cost-of-equity line, and a student would read that as a result (`wacc_with_rate_input`, params `name`). Terminal growth may be changed beside it.
4. **ERP ± 1 SE is not computed when WACC is set.** The run's ERP no longer enters the discount rate, so value per share at ERP ± 1 SE would equal the point and look like precision. The child stores neither bound and no gap; the what-if adds a note `erp_range_not_applicable`, and the report's sensitivity line says "not computed: WACC set directly". The ERP-bound spread warning is skipped for the same reason.
5. **Sources and trace.** The new row gets a `what_if` source with `before` (the parent's WACC output) and empty `parent_sources`; `sources.for_child` adds sources for rows the parent did not have. In the output trace, the `wacc` output's formula is `wacc_set_directly`, from the row alone; the ERP ± 1 SE outputs are left out of the trace when WACC is set.
6. **Lines and notes.** `driven_by` adds `wacc` to every line computed from the discount rate (WACC, discount factors, present values, terminal value, enterprise and equity value, value per share), not to the cost of equity. A new note `wacc_set_directly` (params `before`, `after`) says the cost of equity, beta, ERP and the debt weights no longer drive the rate.

**Point in time.** Nothing is read but the parent's stored rows and outputs, which were point in time on its date.

**LLMs.** None. The student names the rate; `financial_math` does every number.

**Downstream.** A Monte Carlo on a child with WACC set and a risk-premium shock is refused (`DCFInputError`, "a WACC override and a cost-of-equity shift are different questions"); other shocks discount at the set WACC. The sensitivity grid on such a child replaces the set WACC with each axis value, as it does for any run.

## Steps

- **Step 0.** This design doc; no build plan change (a backlog item).
- **Step 1.** `dcf.inputs` reads the optional `wacc` row; `dcf.outputs_and_gaps` skips the ERP bounds when it is set; `math_engine.post_check_notes` skips the ERP-bound spread check; `sources.output_trace` gives `wacc_set_directly` and drops the ERP-bound outputs; `report` says "not computed". Tests (`tests/analysis/test_dcf.py`, `test_sources.py`): a run with a `wacc` row values exactly as `Inputs.wacc_override` does and as the grid's cell at that WACC; rows without it give byte-identical outputs to today; no ERP-bound outputs or gaps with it; the output-trace test (each moved row changes exactly the outputs its trace reaches) passes on rows with a `wacc` row under both terminal methods; a `wacc` row with a cost-of-equity shift is refused. Exit: green.
- **Step 2.** `whatif` takes `wacc`: bounds, the refusal beside a rate input, `delta` from the parent's WACC output, the new row in the child with its source, `driven_by`, the two notes; the CLI accepts `--set wacc=0.09`. Tests (`tests/analysis/test_whatif.py`, `test_report_cli.py`): set and add give the same child; the child reproduces with `runs.reproduce`; its rows equal the parent's plus one `wacc` row; value per share equals `dcf.compute` with `wacc_override`; cost of equity unchanged and not in `driven_by`; refused beside each of the five rate inputs, at 0, below zero, at terminal growth, each storing nothing; terminal growth set beside it works; a second identical call is `reused`; `src.check` passes on the child; the CLI prints the table. Exit: green, ruff clean.
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
- Refusal code `wacc_with_rate_input` (params `name`); `out_of_range` for `wacc` (`low` 0).
- Note codes `wacc_set_directly` (params `before`, `after`) and `erp_range_not_applicable`.
- A child with WACC set has no `value_per_share_erp_minus_1se` / `_plus_1se` output and no gap for them; the app shows "not computed" from the note, never "no value".
- `run_sources`: the `wacc` row's source is `what_if`; the `wacc` output's formula is `wacc_set_directly`.

The terminal-method switch (the rest of #171) waits for the owner's card.
