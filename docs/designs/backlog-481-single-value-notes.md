# Backlog #481 (part 1): how loose a beta is, a cost of debt below the Treasury yield, and the what-if floor

Issue: https://github.com/sonderbot-ar/warren/issues/481 · Branch `backlog-481-single-value-notes` · Version v0.10.19 when merged.

Status: In progress (nov.20.2026).

## Problem

v0.10.14 (#476) gave every single value behind an answer its history. Its review left five follow-ups (#481). This part takes the three that are notes on numbers the engine already computes, and that the value-per-share screen (brief Q3) needs before its mockup:

1. **Beta's standard error (item 1, professor).** A beta history shows a point per month and nothing about how loose each is. A Blume-adjusted beta from 104 weekly returns typically has a standard error of 0.1 to 0.2; a student who sees 1.09 against 1.15 should know the two are not distinguishable.
2. **A cost of debt below the 10-year Treasury yield (item 2, professor).** The cost of debt is interest over the average of two year-end debts (D8): the *embedded* cost of debt raised in past years, not the rate a lender would charge today. When it sits below the risk-free yield, a student may read it as "this company borrows cheaper than the US government". The point should say what it is.
3. **What a floored what-if cost of debt is (item 5, front-end lead).** On a what-if child whose debt changed and whose book cost of debt was below the risk-free rate, `whatif._leverage_rows` replaces the cost of debt with the risk-free rate (`floored_at_risk_free`). Today the child's `cost_of_debt` card shows the book history with no used point and no word on why. The app needs to say the value is the floor, and where the floor came from.

Items 3 (market value of debt from the fair-value note) and 4 (annual diluted counts and a Q4 gap code) need new reads of filings and stay open on #481 for part 2.

No stored number changes; no run's value moves; `reproduce --all` is unaffected (nothing here is read by a run).

## What changes

`inputs_behind` keeps its shape. Three codes join the closed lists in `single_values.py`:

| Code | Where | Params | When |
|---|---|---|---|
| `beta_std_error` | point note, every computed `beta` point | `raw_std_error`, `std_error` (the adjusted beta's: `BLUME_WEIGHT` × raw), `weeks` | always (a computed beta always has one) |
| `below_risk_free` | point note, `cost_of_debt` points | `cost_of_debt`, `risk_free`, `risk_free_date`, `against` (`run_risk_free` or `year_end_yield`) | the point's rate is below the yield it is compared with |
| `floored_at_risk_free` | cell note, `cost_of_debt` on a what-if child | `value` (the floor), `book_value` (the parent's cost of debt), `parent_run_id`, `book_year`, `cell` (`risk_free`, the card whose used point is the floor) | the child's `cost_of_debt` source is a `what_if` with `how` `floored_at_risk_free` |

**The numbers.** `financial_math.ols_beta_std_error(stock, market)`: the slope's ordinary least squares standard error, √(Σ residual² / (n − 2) / Σ (m − m̄)²), on the same weekly pairs `ols_beta` reads; `financial_math.blume_adjusted_std_error(se)` = `BLUME_WEIGHT` × se, since the Blume adjustment is linear in the raw beta (2/3 × raw + 1/3). Plain OLS errors, the same assumption as the beta itself; no Newey–West or heteroskedasticity correction (named in the note's English text and in Alternatives).

**What `below_risk_free` compares with.** The used point (the year the run read) is compared with the run's own `risk_free` row: the rate in the same WACC the student is reading. Every other year is compared with the yield a run dated the day after that fiscal year's end reads (`risk_free_rate`, the last DGS10 close before that day, on the run's pinned download): the yield known when that year's interest was all paid. Nothing after the run's `as_of` is read (every year-end in the series is on or before it; a later one is skipped with no note).

**The floor on a what-if child.** The child's cost-of-debt history is the parent's book history (same company, same date). The book year is read from the `what_if` source's `parent_sources` (the parent's interest filing), so the book year's point is marked as the one the parent used, *not* used by the child: no point is `used`, and the cell note says the value is the floor, equal to the run's `risk_free` row, whose card carries the used point. On a parent whose book cost of debt is below the risk-free rate, the parent's own card already carries `below_risk_free`, so the two cards tell one story.

## Plan

**Step 0. Design doc and review (this doc).** Explainer, analyst, professor; the front-end lead on *Product impact*.

**Step 1. Beta's standard error.** `fm.ols_beta_std_error`, `fm.blume_adjusted_std_error`; `_beta` adds `beta_std_error` to each computed point. Tests: property tests (non-negative; zero on an exact line; unchanged by adding a constant to either series; scales with the stock series' scale; matches a closed-form textbook case) and an example against a hand-computed regression; every computed beta point in the synthetic company carries the note with `std_error` = 2/3 × `raw_std_error`. Exit: tests green.

**Step 2. Cost of debt below the risk-free yield.** `_cost_of_debt` adds `below_risk_free` per the rule above. Tests: on the synthetic company with its yields raised above its book rate, every computed point carries the note with the right `against`; with yields below the book rate, none does; the used point's `risk_free` equals the run's row; no compared yield is dated after `as_of`. Exit: tests green.

**Step 3. The floored what-if.** `_cost_of_debt` reads the book year from a `what_if` source's `parent_sources`; `single_cell` adds `floored_at_risk_free` on a floored child. Tests: a debt what-if on a company whose book rate is below the risk-free rate gives the cell note with `value` equal to the child's `risk_free` row and `book_value` to the parent's `cost_of_debt`, no used point, the book year's point present; a what-if that does not floor gives no note. Exit: tests green.

**Step 4. Real check.** On the restored data, a `value_per_share` answer on each company's newest stored run: every beta point carries `beta_std_error`, list where the used cost of debt is below the risk-free rate, and one real floored what-if child. Exit: all eight companies answer, results below.

## Alternatives considered

- **Newey–West or White standard errors for beta.** Weekly returns show little autocorrelation, and the run's beta uses plain OLS; a different error model than the estimate's own would teach a mismatch. Kept for later if the professor asks; plain OLS is what Damodaran's and Bloomberg's beta pages print.
- **A standard-error band drawn on the beta chart.** A front-end choice; the params give it what it needs (the point ± `std_error`).
- **Compare every cost-of-debt year with the run's risk-free rate.** Rejected: a 2016 cost of debt against a 2026 yield mixes rate regimes; the year-end yield is the like-for-like comparison. The used year uses the run's own rate because that is the comparison inside the WACC the student is reading.
- **Mark a point `used` on a floored child.** Rejected: no cost-of-debt year is the value the child used; marking the parent's year would show a number that is not in the WACC. The cell note points to the risk-free card instead.

## Files to change

`domains/analysis/financial_math.py`, `domains/analysis/single_values.py`, `tests/analysis/test_financial_math_properties.py`, `tests/analysis/test_single_values.py`, `docs/versions.md`, `docs/build-plan.md` (no milestone row changes; backlog only), `docs/team-sync.md`.

## Product impact

Serves brief Q3 (value per share: the discount rate's inputs) and the leverage what-ifs among the *Cambios de supuesto* (brief §3; the debt change of #170, `--set debt=…`). Adds three codes to the closed lists (`beta_std_error`, `below_risk_free` as point notes; `floored_at_risk_free` as a cell note), each with `{code, params, text}` and English text as fallback, so the app owns the Spanish words. Nothing renamed or removed; no existing field changes. The app can draw beta ± `std_error` and must word the two new notes and the cell note.
