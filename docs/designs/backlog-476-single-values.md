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

The code is `domains/analysis/single_values.py`; `inputs.py` calls it for every cell that is not a driver and not an owner choice.

| Cell | Series (measure · frequency · basis) | What each point is | Used point |
|---|---|---|---|
| `risk_free` | `risk_free_yield` · month · latest (primary) | the value `risk_free_rate` gives a run dated the first of each month (the last DGS10 close strictly before that day, as the engine reads it), `years` × 12 month starts before the run's date, then the run's date as the last point (note `run_date`); one part, the DGS10 observation with its date | the run's date |
| `terminal_growth` (when its stored source names `risk_free`) | the `risk_free` series itself | as above; cell note `follows_risk_free` (params `method`, `cell`), so the card says it is a method choice and points to the risk-free card | as above |
| `beta` | `beta` · month · latest (primary) | `fm.blume_adjusted_beta(fm.ols_beta(...))` of `aligned_weekly_returns(conn, ticker, day, 104)`, the engine's call, for the same days as `risk_free` (prices on or before the day, as the engine reads them); one part `raw_beta` whose `period` is the window `first_week/last_week`; `period_end` is the last week; series note `overlapping_windows` | the run's date |
| `erp` | `erp` · year · latest (primary) | `equity_risk_premium(conn, Jan 1 of L+1 + 7 days, first_year)` for each calendar year L of the last `years` complete years (`last_complete_year(as_of)`), `first_year` the run's own stored `erp_first_year`; parts: year L's `^SP500TR_total_return`, `DGS10_bond_total_return` and the estimate's `erp_std_error`; series note `expanding_window` (a good year for stocks raises it) | the run's last complete year |
| `shares` | `shares_outstanding` · date · latest; `diluted_shares` · quarter · latest | every cover-page count dated within `years` of the run's date and every quarter's weighted diluted count, from the history known on the run's date, each × `split_factor(basis, run's price date)` with the engine's basis rule (a cover count from its own date, a statement count from its filing date); the filed count is the part; note `split_adjusted` (params `factor` = new shares per old share, 4.0 = one became four, and `through`) | the count the run counted (matched by item, accession and date); its series is primary |
| `debt`, `cash_and_investments`, `minority_interest` | `<cell>` · quarter · latest (primary) | `math_engine._balance` (D3 and every current-debt rule since #408) run on each `current_assets` date in the window with a fresh `EngineResult` whose `as_of` is the day after that date, on the history known on the run's date (later restatements replace first filings); the point's `period` is the balance date; parts are the filed lines the step counted for that cell; notes are the step's own (`BALANCE_NOTES`: `balance_counted_zero`, `balance_carried_forward`, `debt_current_inside_short_term`, `debt_current_total_in_place`, `debt_current_within_rounding`, `commercial_paper_beside_short_term`); series note `book_value` (params `cell`, `known_on`) | the run's own balance date |
| `cost_of_debt` | `cost_of_debt` · year · latest (primary) | `cost_of_debt_year(history, year)`, the engine's D8 rule, per fiscal year of the window; parts: the interest facts and each year-end's counted debt lines | the fiscal year of the run's interest filing |
| `equity_market_value`, `roll_years` | none | gap `computed_from_other_cells`, params `cell` and `inputs` (the `{name, period}` rows of its stored derived source: `price` and `shares`; `revenue_seed` of the seed quarter) | — |

`price` is not reached by any output (it enters only through `equity_market_value`), so it has no card; the equity value's card points to `shares` and to the price row.

**Closed lists for the app** (constants in `single_values.py`, tested): a point the rule cannot compute has `missing` code `not_computable` with `params.reason` from `MISSING_REASONS`: `too_few_return_weeks`, `no_risk_free_rate`, `no_price_on_date`, `erp_too_few_years`, `market_data_not_loaded`, `market_data_not_refreshed`, `market_year_end_missing`, `market_data_error` (any other market failure, its own code in `params.error_code`), `no_balance_sheet`, `balance_item_not_reported`, `balance_item_negative`, `securities_exceed_current_assets`, `no_interest_reported`, `average_debt_not_positive`. These are chart notes, not a refused run's advice (the front-end lead's point on `erp_too_few_years`). Point notes: `BALANCE_NOTES` above and `run_date`, `split_adjusted`, `run_read_differently` (the used point differs from the run's row: params `period`, `run_value`, `value`). Cell notes: `follows_risk_free`, `computed_from_other_cells`. Series notes: `book_value`, `overlapping_windows` (params `weeks`, `step`), `expanding_window` (params `first_year`).

Owner choices keep `owner_choice`. A run with no debt (`cost_of_debt` 0 by `no_debt`) still gets the cost-of-debt history; it has no used point.

## Plan

**Step 0. Design doc and review (this doc).** Explainer, analyst, professor, and the front-end lead on *Product impact*.

**Step 1. One engine function shared, not copied.** Move the body of `math_engine._cost_of_debt`'s year loop into `cost_of_debt_year(history, year)`, returning the rate and the facts, and call it from `_cost_of_debt` (no value moves). Tests: the existing engine tests, and `reproduce --all` on the restored data. Exit: every stored run reproduces to the cent.

**Step 2. The market cells.** `risk_free`, `terminal_growth` (risk-free method), `beta`, `erp`, with the run's fetches pinned. Tests (synthetic company): the last point equals the run's row exactly and is the only `used` point; a point never reads a price or yield dated on or after its own date; `years` sets 12 × `years` monthly points; an ERP year short of ten years is `missing` with `erp_too_few_years`.

**Step 3. The balance-sheet cells.** `debt`, `cash_and_investments`, `minority_interest`, `cost_of_debt`, `shares`. Tests: the used point equals the run's row exactly; parts sum to the point; a balance filed after `as_of` never appears; a split-adjusted count carries `split_adjusted`; every code is in the closed lists; the cost-of-debt used year equals the run's.

**Step 4. Real check.** On the restored data, a `value_per_share` answer on every company's stored run: no `history_not_built` left, each used point equals the run's row (to 1e-9), and timing noted. Exit: all eight companies pass.

## Alternatives considered

- **Re-implement the balance and share rules inside `inputs.py`.** Rejected: D3 has six rules added by backlog items since #408; a copy would drift. Calling the engine's own step on each date keeps one rule.
- **Beta and the risk-free rate at fiscal year ends.** Rejected: market data is daily and calendar-based, and a monthly line shows how the beta moved through the year the student is looking at; fiscal year ends would give five points for a ten-year-old's guess.
- **Equity value history (price × shares by month).** Deferred: both inputs have their own cards; the product of two charts adds no teaching and the shares' dates do not line up with the months.

## Files to change

`domains/analysis/single_values.py` (new), `domains/analysis/inputs.py`, `domains/analysis/math_engine.py` (`cost_of_debt_year`), `domains/analysis/__main__.py` (a missing point prints its reason), `tests/analysis/test_single_values.py` (new), `tests/analysis/test_inputs.py`, `docs/versions.md`, `docs/build-plan.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q3 (value per share) and Q4 (the discount rate) and every answer that reaches the discount rate or the bridge to equity: their cards get history instead of "coming soon". Nothing renamed or removed; no stored number changes. For the app: `history_not_built` no longer appears on today's runs; the new codes to word are the closed lists above (`not_computable` and its fourteen reasons, the point, cell and series notes); new series measures `risk_free_yield`, `beta`, `erp`, `shares_outstanding`, `diluted_shares`, `debt`, `cash_and_investments`, `minority_interest`, `cost_of_debt`; new part names `raw_beta`, `^SP500TR_total_return`, `DGS10_bond_total_return`, `erp_std_error` (so the ERP card can draw the ± one standard error band of brief Q3), the DGS10 observation and the balance lines' own names; new frequencies `month` and `date`; calendar points have `fiscal_year` and `fiscal_period` null; the beta window is the `raw_beta` part's `period` (`first_week/last_week`), for brief Q4's "method and window".

## Results

Real data, restored snapshot of nov.17 (schema 23), every company on 2026-10-30.

- **No single value is left without history.** On a `value_per_share` answer, every company's run has history for the risk-free rate, terminal growth, beta, ERP, debt, cash, minority interest, cost of debt and shares; the equity value and roll years point to their inputs. At 3, 5 and 10 years.
- **The used point equals the run's row (to 1e-9) on every run built under today's rules**: AAPL, MSFT, WMT (`_1`) and CAT, JNJ, KO, PG, XOM (`_2`, fresh runs stored for this check). On the older stored runs of CAT, JNJ, KO, PG and XOM (`_1`, built before the current-debt rules of #341–#430) the debt and cost-of-debt used points differ from the run and carry `run_read_differently` (CAT 2026-06-30: 43.3B today, 36.2B in the run), the same five companies #471 found; so does XOM_2025-12-01_1. Market points always agree.
- **What a student will see.** Apple's 10-year Treasury yield goes from 1.55% (Nov 2021) to 4.98% on the run's date; its beta from 1.00 to 1.02; the ERP over five year-ends from 5.26% (2021) to 6.19% (2025). Apple's cost of debt has no point after FY2023: the company stopped reporting interest expense, so the run uses FY2023 (3.37%) and the chart says `no_interest_reported` for the later years. Every company's latest fiscal year has the same reason, because its 10-K is not filed yet.
- **Speed**: 2.6–10.3 s per full answer (part 1 alone was 3.0–9.4 s); the single values add about a second.
- **Step 1 is a refactor**: 909 of 909 stored runs reproduce to the cent; reading rules stay v11 (row added to `reading_rules.md`).
- Tests: `tests/analysis/test_single_values.py`, 12 tests; two #471 tests updated (no single value says `history_not_built` any more). Full suite 2,647 passed, 10 skipped.

## Review notes

Design review, nov.19.2026.

- **Explainer**: 16 points where it had to guess; taken: the run's methods named in the table, the strict vs on-or-before reading of yields and prices (the engine's own), how a run is known to follow the risk-free rate (its stored derived source), the beta window's end, the ERP's first day, each window's length, `_balance`'s fresh result per date, the label of a balance point (its date), the cost-of-debt reason codes, a no-debt run, the closed lists, `run_read_differently` on single values, `computed_from_other_cells`'s `inputs`. `price` dropped as a cell: no output reaches it.
- **Analyst**: GO, no blockers. Taken: the fresh result per date stated; balance points labelled as known on the run's date (`book_value` gains `known_on`); carried-forward notes kept on each point; reason codes for skipped cost-of-debt years; no duplicate last point for a run dated the first of a month (the month list skips it). Filed: CAT's 7.12B principal due within a year counted as zero (#480); annual diluted counts and a Q4 gap code (#481).
- **Professor**: PASS. Taken: notes for the overlapping beta windows and the expanding ERP window (it rises after good years), the ERP's standard error on each point, terminal growth labelled a method choice, book value named. Filed on #481: the beta's standard error, a note when the cost of debt is below the Treasury yield, market value of debt.
- **Front-end lead**: NO-GO on two blockers, both taken: every `missing` reason and note is now a closed list in code and in this doc (and refusal codes appear only as a reason, never as a refused run's advice); terminal growth carries `follows_risk_free`. Suggestions taken: the ERP standard error, the `run_date` note on the last point, the split factor's direction. On #481: what `used` means on a floored what-if run.
- **Gatekeeper**: GO, no blockers. Taken before merge: two market refusal codes the list missed (`market_data_not_refreshed`, `market_year_end_missing`) and a catch-all `market_data_error` so the list stays closed; each stored download the run names is pinned on its own, not all-or-none. Left for #481: a real-data test of the closed lists.
