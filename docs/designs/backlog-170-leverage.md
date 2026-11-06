# Backlog #170: a leverage what-if (more or less debt, with beta relevered)

Issue: https://github.com/sonderbot-ar/warren/issues/170 · Branch `backlog-170-leverage` · Version v0.9.27 when merged · Part 1 of 2.

## Problem

Brief §2 (`docs/product/brief.md`) lists debt among the inputs a student may change. The what-if (v0.9.9, `domains/analysis/whatif.py`) refuses it on purpose: one row, `debt`, is both the WACC's debt weight and the claim on the firm, and beta is not relevered. The #141 review measured what a naive change does: on WMT_2026-10-15_1, debt +$50bn moved WACC 9.15% → 8.89% and value per share $30.03 → $24.99. More debt looked cheaper because the equity's risk stayed where it was; and on a run with no debt, whose stored cost of debt is 0 ("not used (weight 0)", `math_engine._cost_of_debt`), the new debt would cost nothing.

A student's question is "if Walmart borrowed $50bn to buy back shares, what is a share worth?" Answering it honestly needs three things the naive change lacks: what the money is for, a beta that rises with leverage, and a price for the new debt.

## Scope: part 1 and part 2

- **Part 1 (this item):** the debt swapped with equity at the as-of share price (a buyback, or new shares that repay debt), beta relevered by Hamada's rule, the cost of debt held at the company's own unless the student sets it, and refusals where an answer would mislead.
- **Part 2 (a follow-up issue, filed with this PR):** a cost of debt that moves with leverage on its own: a synthetic rating from interest coverage and a dated spread by rating (Damodaran's method, *Applied Corporate Finance*, ch. 8). It needs a dated, sourced spread table for every case date, which is new data behind an adapter and its own design. Until then, part 1 says plainly that the cost of debt was held and what that leaves out.

## What changes

1. **`Change("debt", delta=…)` or `value=…`, with `use="buyback"`.** `Change` gains `use`, required for `debt` and refused on any other input (`use_on_other_input`). The one use in part 1 is `buyback`: the change in debt is swapped with equity at the run's as-of price (the stored `price` row): more debt buys shares back, less debt is repaid with new shares. Other uses are refused with `debt_use_not_supported` (params `use`, `supported`): `cash_kept` (the engine weights gross debt, so debt held as cash would raise beta and the debt weight while net debt and the business are unchanged; it needs net-debt weights, a design of its own) and `acquisition` (it changes the cash flows, which a what-if holds). A debt change without a use is refused with `debt_use_needed`.
2. **The rows the child changes** (ΔD = new debt − the parent's debt; price P = the parent's `price` row):
   - `debt`: D′ = D + ΔD, at least 0 (`out_of_range`, low 0 included).
   - `shares`: N′ = N − ΔD ÷ P (how `buyback`); `equity_market_value`: E′ = P × N′ (how `buyback`), so E′ = E − ΔD at the same price. If E′ would not be above zero the change is refused with `buyback_exceeds_market_value` (params `debt_change`, `equity_market_value`): a buyback can't retire more than every share.
   - `beta`: relevered (how `relevered`), Hamada (1972) with the tax term, as Damodaran teaches it (*Investment Valuation*, ch. 8): unlevered βu = βL ÷ (1 + (1 − t) D ÷ E) on the parent's rows, then βL′ = βu × (1 + (1 − t′) D′ ÷ E′) on the child's, with t the `debt_tax_rate` and E the market value of equity. D is book debt, as the engine's WACC weights it (brief §5 says so); two new `financial_math` functions, `unlevered_beta` and `relevered_beta`, with property tests.
   - `cost_of_debt`: held at the parent's unless the student sets or adds to it in the same what-if. A run whose stored debt is 0 has cost of debt 0 as a placeholder, so new debt on it is refused with `cost_of_debt_needed` unless the student also sets `cost_of_debt`.
   - Nothing else: the cash flows, cash, minority interest and the rate inputs are the parent's. EV changes only through WACC (Modigliani–Miller: financing does not change the operating cash flows), and equity per share changes through WACC, net debt and the share count.
3. **Inputs that follow and so can't be changed beside it.** `beta` and `shares` are computed by the leverage change; naming either beside `debt` is refused with `follows_debt_change` (params `name`). `wacc` set directly is refused beside it with the existing `wacc_with_rate_input` (params `name` `debt`), since a set rate ignores the weights. `cost_of_debt`, `debt_tax_rate`, the drivers, cash, minority interest, terminal growth and the terminal-formula switch may be changed beside it.
4. **What-if notes.** `leverage_changed` (params `use`, `debt_before`, `debt_after`, `shares_before`, `shares_after`, `price`, `beta_before`, `beta_after`, `unlevered_beta`): the swap, the price it was done at, and beta relevered by Hamada's rule. `buyback_at_market_price` (params `price`, `value_per_share_before`): shares are bought or sold at the market price, not at Warren's value, so when Warren's value per share is above the price a buyback moves value to the shareholders who stay, and below it moves value away; this is a reason value per share moves that is not a change in the business. `cost_of_debt_held_on_leverage` (params `cost_of_debt`), when debt rises and the student did not set the cost of debt: the company's past cost is held, lenders would charge more as debt rises, and with that and no cost of financial distress the fall in WACC shown is the interest tax shield alone, so it overstates the gain (Damodaran, *Applied Corporate Finance*, ch. 8).
5. **Sources and trace.** Each changed row gets a `what_if` source with `before` and `how` (`set`/`add` for debt, `buyback`, `relevered`); `sources.for_child` already does this. A copied row derived from a changed one names the parent's row, as today.
6. **`driven_by`.** `debt`, `beta`, `shares` and `equity_market_value` are added to the lines they feed: cost of equity (beta), WACC and every line discounted by it (debt, beta, market value), net debt, equity value and value per share (debt), value per share (shares).

**Point in time.** Nothing is read but the parent's stored rows and outputs, which were point in time on its date; the price is the parent's `price` row.

**LLMs.** None. The student names the debt; `financial_math` does every number.

**Downstream.** The child is an ordinary run: `runs.reproduce`, the sensitivity grid and a Monte Carlo read its rows like any other. No migration.

## Steps

- **Step 0.** This design doc; no build plan change (a backlog item).
- **Step 1.** `financial_math.unlevered_beta(beta, debt, equity_market_value, tax_rate)` and `relevered_beta(unlevered, debt, equity_market_value, tax_rate)`. Tests (`tests/analysis/test_financial_math.py`, `test_financial_math_properties.py`): no debt leaves beta unchanged; unlever then relever at the same structure gives the beta back (to 1e-12); relevered beta rises with D ÷ E and falls with the tax rate; refusals for equity at or below zero, negative debt, a tax rate outside [0, 1); arrays work. Exit: green.
- **Step 2.** `whatif` takes `debt` with `use="buyback"`: the rows that follow, the bounds and refusals, the notes, `driven_by`; the CLI's `--debt-use buyback`. Tests (`tests/analysis/test_whatif.py`, `test_report_cli.py`): debt +ΔD equals hand-edited rows (debt, shares, market value, Hamada beta) valued by `dcf`; the child reproduces; its rows differ from the parent's in exactly those four; ΔD = 0 gives the parent's value per share to the cent; set and add give the same values; more debt raises beta and cost of equity; the Modigliani–Miller check: with t = 0 and the cost of debt equal to the risk-free rate (Hamada's riskless debt), WACC is the same at any debt level; and then a buyback at a price equal to Warren's value per share leaves value per share unchanged; each refusal stores nothing; a second identical call is `reused`; `src.check` passes on the child; the CLI prints the table. Exit: green, ruff clean.
- **Step 3.** Real data on the restored snapshot: on the latest stored run of each company, ΔD = 0 gives the parent's value per share to the cent; then debt +10% of market value and the WMT_2026-10-15_1 +$50bn case of the #141 review, with and without a set cost of debt; every child reproduces; `reproduce --all` still passes. Results below. Exit: every child reproduces; the numbers are written here.

**Exit criterion:** all tests pass; Step 3's children reproduce to the cent and the zero-change identity holds on every company.

## Alternatives considered

- **Harris–Pringle (βL = βu (1 + D ÷ E), no tax term)**, the rule for a company that keeps its debt ratio steady (Koller, Goedhart and Wessels, *Valuation*, appendix on leverage and beta). A defensible choice; Hamada with the tax term is what Damodaran teaches with the cost-of-capital approach and what the issue names, and it is one line to switch later. Rejected for part 1, named in the note's text.
- **A synthetic rating now.** It is the right cost of debt, but it needs a dated spread table for every case date (new data, an adapter, sources); it is part 2.
- **Debt as a plain input with beta held** (the naive change). Rejected in #141 for the reason above.
- **Market-value weights for debt.** The engine weights debt at book (brief §5); changing that moves every stored WACC and is not this item's question.

## Files to change

Changed: `domains/analysis/financial_math.py`, `domains/analysis/whatif.py`, `domains/analysis/__main__.py` (`--debt-use`), tests in `tests/analysis/`. At merge: `docs/versions.md`, `docs/team-sync.md`, `docs/product/brief.md` (§2's input list: debt with a use).

## Product impact

Serves brief §2's "debt" input (the what-if behind questions 7 and 8). Adds, with nothing renamed or removed:

- `Change("debt", value=… | delta=…, use="buyback")`; `Change` gains `use` (None for every other input). Change rows: `debt` (`set`/`add`), `shares` and `equity_market_value` (`buyback`), `beta` (`relevered`).
- Refusal codes: `debt_use_needed`, `debt_use_not_supported` (`use`, `supported`), `use_on_other_input` (`name`), `buyback_exceeds_market_value` (`debt_change`, `equity_market_value`), `cost_of_debt_needed`, `follows_debt_change` (`name`); `wacc_with_rate_input` can now carry `name` `debt`; `out_of_range` for `debt` (`low` 0).
- What-if note codes: `leverage_changed`, `buyback_at_market_price`, `cost_of_debt_held_on_leverage` (params above).
- No change to any stored run, run note code or output name.
