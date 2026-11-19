# Backlog #476: history for the single values behind an answer

Issue: https://github.com/sonderbot-ar/warren/issues/476 · Branch `backlog-476-single-values` · Version v0.10.14 when merged.

## Problem

Part 1 (#471, v0.10.13) gave every driver cell of an answer its history. The single values (the discount rate's inputs, the bridge from firm value to value per share) come back with their rows and the gap code `history_not_built`. The owner asked for a chart behind every cell of any answer (nov.19.2026), and the front-end lead's condition on #471 is that these histories land before the Q3 (value per share) screen's mockup goes to the owner. Without them, a student sees a beta of 1.09 or a cost of debt of 3.4% with nothing to compare it to.

## What changes

`inputs_behind(conn, run_id, outputs, years)` keeps its shape. Cells that today carry `history_not_built` gain `history` series instead. Every value is computed by the engine's own functions on the run's own downloads (the market fetches the run's hashes name are pinned, as `reproduce` does), and point-in-time: nothing dated or filed after the run's `as_of` is read.

Two small additions to the shapes, both additive:

- `Point.fiscal_year` and `Point.fiscal_period` may be `None` on a calendar series (market data is by calendar date, not fiscal period). Such a point's `period` is an ISO date (`2026-09-01`) or a calendar year (`2025`).
- `Series.frequency` gains `month` (market series) and `date` (cover-page share counts, dated by the cover, not by a quarter).

### History per single value

| Cell | Series (measure · frequency · basis) | What each point is | Used point |
|---|---|---|---|
| `risk_free` | `risk_free_yield` · month · latest (primary) | the value `risk_free_rate` gives a run dated the first of each month (the last DGS10 close before it), `years` × 12 months, then the run's own date as the last point | the run's own date |
| `terminal_growth` (when it follows the risk-free rate) | the same series as `risk_free` | as above | as above |
| `beta` | `beta` · month · latest (primary) | the run's method (Blume-adjusted OLS of 104 weekly total returns vs the S&P 500 total return index) on a run dated the first of each month, then the run's date; parts `raw_beta` and the weeks' first and last dates in notes | the run's date |
| `erp` | `erp` · year · latest (primary) | the run's method (geometric premium from the run's `erp_first_year`) with the window ending at each calendar year L of the last `years` complete years, as known on the first day L counts as complete; parts: that year's S&P 500 total return and 10-year Treasury total return, so the chart shows what each new year added | the run's last complete year |
| `price` | `price` · month · latest (primary) | the close on or before the first of each month, put on the run's share basis (÷ the split factor up to the run's price date), then the run's close | the run's date |
| `shares` | `shares_outstanding` · date · latest; `diluted_shares` · quarter · latest | every cover-page count, and every quarter's weighted diluted count, dated within the window and filed by `as_of`, each adjusted for splits to the run's price date with the engine's own basis rule (a cover count from its own date, a statement count from its filing date); a split adjustment adds the note `split_adjusted` with the factor | the count the run used (the cover page when it has one, else the diluted fallback); that series is primary |
| `debt`, `cash_and_investments`, `minority_interest` | `<cell>` · quarter · latest (primary) | the engine's balance step (`_balance`, D3 and every current-debt rule since #408) run on each balance date in the window, reading the history known on the run's `as_of`; parts are the balance lines it counted, with their filings; its notes (`balance_counted_zero`, `debt_current_inside_short_term`, …) go on the point; a balance date the step refuses has `missing` with the engine's refusal code | the run's own balance date |
| `cost_of_debt` | `cost_of_debt` · year · latest (primary) | the run's rule (D8): that fiscal year's interest over the average of the two year-end debts, by the same function the engine uses; parts: interest and each year-end's debt lines | the fiscal year the run used |
| `equity_market_value`, `roll_years` | none | computed from other cells (price × shares; the days from the last quarter end): gap `computed_from_other_cells` with the input rows in `params`, so the app points to their cards | — |

Owner choices keep `owner_choice`. A single value whose rule is "none" (no debt: `cost_of_debt` 0 by `no_debt`) still gets its history, since the student may ask why it is zero.

## Plan

**Step 0. Design doc and review (this doc).** Explainer, analyst, professor, and the front-end lead on *Product impact*.

**Step 1. One engine function shared, not copied.** Move the body of `math_engine._cost_of_debt`'s year loop into `cost_of_debt_year(history, year)`, returning the rate and the facts, and call it from `_cost_of_debt` (no value moves). Tests: the existing engine tests, and `reproduce --all` on the restored data. Exit: every stored run reproduces to the cent.

**Step 2. The market cells.** `risk_free`, `terminal_growth` (risk-free method), `beta`, `erp`, `price`, with the run's fetches pinned. Tests (synthetic company): the last point equals the run's row exactly and is the only `used` point; a point never reads a price or yield dated on or after its own date; `years` sets 12 × `years` monthly points; an ERP year short of ten years is `missing` with `erp_too_few_years`; price points are on the run's share basis across a split.

**Step 3. The balance-sheet cells.** `debt`, `cash_and_investments`, `minority_interest`, `cost_of_debt`, `shares`. Tests: the used point equals the run's row exactly; parts sum to the point; a balance filed after `as_of` never appears; a refused balance date is `missing` with its code; a split-adjusted count carries `split_adjusted`; the cost-of-debt used year equals the run's.

**Step 4. Real check.** On the restored data, a `value_per_share` answer on every company's stored run: no `history_not_built` left, each used point equals the run's row (to 1e-9), and timing noted. Exit: all eight companies pass.

## Alternatives considered

- **Re-implement the balance and share rules inside `inputs.py`.** Rejected: D3 has six rules added by backlog items since #408; a copy would drift. Calling the engine's own step on each date keeps one rule.
- **Beta and the risk-free rate at fiscal year ends.** Rejected: market data is daily and calendar-based, and a monthly line shows how the beta moved through the year the student is looking at; fiscal year ends would give five points for a ten-year-old's guess.
- **Equity value history (price × shares by month).** Deferred: both inputs have their own cards; the product of two charts adds no teaching and the shares' dates do not line up with the months.

## Files to change

`domains/analysis/inputs.py`, `domains/analysis/math_engine.py` (`cost_of_debt_year`), `tests/analysis/test_inputs.py`, `docs/versions.md`, `docs/build-plan.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q3 (value per share) and every answer that reaches the discount rate or the bridge to equity: their cards get history instead of "coming soon". Nothing renamed or removed; no stored number changes. For the app: `history_not_built` no longer appears for these cells; new gap code `computed_from_other_cells` (params `inputs`, the rows to point to); new point note `split_adjusted` (param `factor`); new series measures `risk_free_yield`, `beta`, `erp`, `price`, `shares_outstanding`, `diluted_shares`, `debt`, `cash_and_investments`, `minority_interest`, `cost_of_debt`; new frequencies `month` and `date`; calendar points have `fiscal_year` and `fiscal_period` null; engine refusal codes may appear as a point's `missing` (they are already in the Spanish catalogue).
