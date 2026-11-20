# Backlog #481 (part 1): how loose a beta is, a cost of debt below the Treasury yield, and the what-if floor

Issue: https://github.com/sonderbot-ar/warren/issues/481 · Branch `backlog-481-single-value-notes` · Version v0.10.19 when merged.

Status: Built (nov.20.2026); PR open.

## Problem

v0.10.14 (#476) gave every single value behind an answer its history. Its review left five follow-ups (#481). This part takes the three that are notes on numbers the engine already computes, and that the value-per-share screen (brief Q3) needs before its mockup:

1. **Beta's standard error (item 1, professor).** A beta history shows a point per month and nothing about how loose each is. A Blume-adjusted beta from 104 weekly returns has a standard error of about 0.07 to 0.13 on the eight companies (Step 4); a student should know how far a point may be from the true beta.
2. **A cost of debt below the 10-year Treasury yield (item 2, professor).** The cost of debt is interest over the average of two year-end debts (D8): the *embedded* cost of debt raised in past years, not the rate a lender would charge today. When it sits below the risk-free yield, a student may read it as "this company borrows cheaper than the US government". The point should say what it is.
3. **What a floored what-if cost of debt is (item 5, front-end lead).** On a what-if child whose debt changed and whose book cost of debt was below the risk-free rate, `whatif._leverage_rows` replaces the cost of debt with the risk-free rate (`floored_at_risk_free`). Today the child's `cost_of_debt` card shows the book history with no used point and no word on why. The app needs to say the value is the floor, and where the floor came from.

Items 3 (market value of debt from the fair-value note) and 4 (annual diluted counts and a Q4 gap code) need new reads of filings and stay open on #481 for part 2.

No stored number changes; no run's value moves. The notes are computed when an answer is read and never stored, so `reproduce` is untouched.

## What changes

`inputs_behind` keeps its shape. Three codes join the closed lists in `single_values.py`:

| Code | Where | Params | When |
|---|---|---|---|
| `beta_std_error` | point note, every `beta` point with a computed value (a `missing` point has none) | `raw_std_error`, `std_error` (the adjusted beta's: `BLUME_WEIGHT` × raw), `weeks` | always on a computed point |
| `below_risk_free` | point note, `cost_of_debt` points | `cost_of_debt`, `risk_free`, `risk_free_date`, `against` (`run_risk_free` or `year_average_yield`); on `year_average_yield` also `risk_free_from` and `observations` | the cost of debt is strictly below the yield it is compared with (`<`, the floor's own test) |
| `floored_at_risk_free` | cell note, `cost_of_debt` on a what-if child | `value` (the floor: the child's own `risk_free` row), `book_cost_of_debt` (the parent's stored cost of debt, the what-if source's `before`; always set), `book_year` (`FY…` of the parent's interest filing; `None` when the parent's sources name none), `parent_run_id`, `cell` (`risk_free`, the card holding the floor), `risk_free_changed` (true when the child's risk-free row is itself a what-if value, so that card has no used history point either) | the child's `cost_of_debt` source is a `what_if` with `how` `floored_at_risk_free`; always emitted then |

**The numbers.** `financial_math.ols_beta_std_error(stock, market)`: the slope's ordinary least squares standard error, √(Σ residual² / (n − 2) / Σ (m − m̄)²), on the same weekly pairs `ols_beta` reads; `financial_math.blume_adjusted_std_error(se)` = `BLUME_WEIGHT` × se, since the Blume adjustment is linear in the raw beta (2/3 × raw + 1/3; Var(aX + b) = a² Var(X)). Plain OLS errors, the same assumption as the beta itself. The note's English text says the error is scaled by the fixed Blume weight and is not a test of the change from last month, since neighbouring months share 100 of their 104 weeks.

**What `below_risk_free` compares with.** The used point (the year the run read) compares the run's own two rows, `cost_of_debt` and `risk_free`: the rates in the same WACC the student is reading, and exactly the test `whatif._would_floor` makes, so a debt what-if floors if and only if the parent's used point carries the note (when the student does not also move the risk-free rate). On an older run whose year now reads differently, the point also carries `run_read_differently`. Every other year is compared with the average 10-year yield over that fiscal year (every DGS10 close from 364 days before the year end through the year end, on the run's pinned download, `market.yields.yields_through`, averaged with `financial_math.mean`): interest over average debt is a flow over the year, so one day's yield is not like for like (analyst). It is still a rough benchmark: a year's interest reflects coupons set at issue, short-term borrowing and swaps (professor), and the note's text says so and says the note is common. Nothing after the run's `as_of` is read; a year whose end is on or after it gets no note.

**The floor on a what-if child.** The child's cost-of-debt history is the parent's book history (same company, same date). No point is `used`; the cell note's `book_year` names the year the parent used (read from the `what_if` source's `parent_sources`), and `value` is the child's own `risk_free` row, whose card holds the floor. When the student did not move the risk-free rate, the parent's used point carries `below_risk_free`, so the two cards tell one story. The note's text says the floor is a minimum, not an estimate: more debt usually costs more, so the what-if value is on the high side (professor; a cost of debt that rises with leverage is #232).

## Plan

**Step 0. Design doc and review (this doc).** Explainer, analyst, professor; the front-end lead on *Product impact*.

**Step 1. Beta's standard error.** `fm.ols_beta_std_error`, `fm.blume_adjusted_std_error`. Tests (`tests/analysis/test_financial_math_properties.py`): property tests (not negative; zero on an exact line; unchanged by adding a constant to either series; scales with the stock series), a hand-computed regression (x = 1..5, y = 2, 4, 5, 4, 5: slope 0.6, error √0.08), the Blume error equals the adjustment's slope, and the same refusals as `ols_beta`. Exit: tests green. Done.

**Step 2. The two point notes.** `_beta` adds `beta_std_error` to each computed point; `_cost_of_debt` adds `below_risk_free` per the rule above; `market.yields.yields_through`. Tests (`tests/analysis/test_single_values.py`): every computed beta point carries the note with `std_error` = 2/3 × `raw_std_error`; Test Corp (4% book against a 3% yield) has no `below_risk_free`; with half the interest (2%), every computed year carries it, the used year against the run's row and the others against the year's average yield (window inside the fiscal year, at least 50 weekly yields, nothing after `as_of`). Exit: tests green. Done.

**Step 3. The floored what-if.** `single_cell` adds `floored_at_risk_free` on a floored child. Tests: a debt what-if with the risk-free rate set to 5% gives the cell note with `value` equal to the child's `risk_free` row and `book_cost_of_debt` to the parent's cost of debt, `book_year` FY2019, `risk_free_changed` true, no used point and the book year present; a what-if that does not floor has no note; an older run whose stored cost of debt (2.5%) differs from today's read (4%) carries the note on its used year from its own rows, and its debt what-if floors. Exit: tests green. Done.

**Step 4. Real check.** On the restored data, a `value_per_share` answer on each company's newest stored run, and one floored what-if child per company. Exit: all eight companies answer; results below. Done.

## Alternatives considered

- **Newey–West or White (1980) standard errors for beta.** Weekly returns show little autocorrelation, and the run's beta uses plain OLS; a different error model than the estimate's own would teach a mismatch. Plain OLS is what the Bloomberg beta page prints for the raw beta ("Std. Error of Beta", reproduced in Damodaran, *Investment Valuation*, 3rd ed., ch. 8).
- **A Bayesian error for the adjusted beta (Vasicek, 1973).** 2/3 × the raw error is the spread of the adjusted estimator with the weight held fixed, not the uncertainty about the true beta after shrinking toward 1. Kept as a plain scaled error and said so in the text; the Bayesian version needs a cross-section of betas Warren does not hold.
- **A standard-error band drawn on the beta chart.** A front-end and owner choice (the brief keeps beta a point value); the params give it what it needs.
- **Compare every cost-of-debt year with the run's risk-free rate.** Rejected: a 2016 cost of debt against a 2026 yield mixes rate regimes. The used year uses the run's own rate because that is the comparison inside the WACC the student is reading.
- **The yield on the year's last day** (the first draft). Rejected after the analyst's review: DGS10 averaged about 2.9% in 2022 but closed it near 3.9%, so the note would turn on one day.
- **A tolerance on "below"** (professor). Rejected: the floor uses a strict `<` and the note must agree with it; both rates are in the params, so the app can show the gap.
- **Mark a point `used` on a floored child.** Rejected: no cost-of-debt year is the value the child used; marking the parent's year would show a number that is not in the WACC. The cell note points to the risk-free card instead.

## Files to change

`domains/analysis/financial_math.py`, `domains/market/yields.py` (`yields_through`), `domains/analysis/reading_rules.md` (two rows, version unchanged: no run reads a different figure), `domains/analysis/single_values.py`, `tests/analysis/test_financial_math_properties.py`, `tests/analysis/test_single_values.py`, `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q3 (value per share: the discount rate's inputs) and the leverage what-ifs among the *Cambios de supuesto* (brief §3; the debt change of #170). Adds three codes to the closed lists (`beta_std_error`, `below_risk_free` as point notes; `floored_at_risk_free` as a cell note), each with `{code, params, text}` and English text as fallback, so the app owns the Spanish words. Nothing renamed or removed; no existing field changes. `std_error` is a note on how loose each beta point is; it does not feed the cost of equity or the value-per-share range (brief §4 keeps beta a point value; showing it as a band is a brief change for the front-end team and the owner). Expect `below_risk_free` on the used year of seven of the eight companies today (Step 4): it is common, and its text says so.

## Reviews (nov.20.2026)

- **Explainer**: 16 gaps, all answered in the text above: strict `<`; only points with a computed beta; the averaging window and what is read; the params of each comparison; `book_year` as the marker of the parent's year, `None` when no interest filing; the child's own risk-free row; the notes are computed at read time and not stored; where the tests live. The English is fallback text; the app's Spanish goes through the front-end team's own owner sign-off.
- **Analyst** (GO, no blockers). Taken: the floor follows the child's risk-free rate; the used year compares the run's own stored rows, as the floor does (a test pins this on an older run); a year's average yield instead of its last day; the standard-error range in the Problem (0.07 to 0.13, measured in Step 4); the source in Alternatives; the note says it is common. Filed: Walmart's interest leaves out finance-lease interest while its debt includes finance leases, so its book cost of debt reads low (#497).
- **Professor** (approve with notes). All taken in the texts and Alternatives: the adjusted error is the estimator's spread at a fixed weight (Vasicek, 1973); overlapping months are not a test of change; the year's yield is a rough benchmark; the benchmark is named in each note; the floor is a minimum, so the what-if value is optimistic; `book_value` renamed `book_cost_of_debt` (it clashed with the series note `book_value`). The synthetic-rating idea is already #232.
- **Front-end lead** (accept with three changes, all taken): the child's own risk-free row and `risk_free_changed`; `book_year` `None` with the note always emitted; `std_error` is a note, not a band.

## Step 4 results: real check (nov.20.2026)

Restored snapshot `warren-20261119T102307Z`; `reproduce --all`: 909 of 909 runs to the cent. A `value_per_share` answer on each company's newest run (all dated 2026-10-30), and, on a copy of the database, a debt what-if of +$10bn (use buyback) on each:

| Company | Beta (used) | Its standard error | Used cost of debt | Risk-free | Years noted below the yield | +$10bn debt what-if |
|---|---|---|---|---|---|---|
| AAPL | 1.02 | 0.106 | FY2023 3.37% | 4.98% | FY2023 | floored, book FY2023 |
| CAT | 1.07 | 0.125 | FY2025 4.51% (run: 5.42%) | 4.98% | FY2022, FY2023 | not floored |
| JNJ | 0.32 | 0.090 | FY2025 2.30% | 4.98% | FY2022–FY2025 | floored, book FY2025 |
| KO | 0.38 | 0.073 | FY2025 3.67% | 4.98% | FY2022–FY2025 | floored, book FY2025 |
| MSFT | 1.08 | 0.112 | FY2026 3.11% | 4.98% | FY2023–FY2026 | floored, book FY2026 |
| PG | 0.47 | 0.074 | FY2026 2.56% | 4.98% | FY2023–FY2026 | floored, book FY2026 |
| WMT | 0.68 | 0.112 | FY2026 4.76% | 4.98% | FY2026 | floored, book FY2026 |
| XOM | 0.29 | 0.113 | FY2025 1.41% | 4.98% | FY2022–FY2025 | floored, book FY2025 |

Every computed beta point carries `beta_std_error`; each answer takes 1.2 to 2.5 s. CAT shows why the used year compares the run's own rows: its stored run (built before #341, so it counted current debt as zero, #485) holds 5.42%, above the yield, so its what-if does not floor and its used point carries only `run_read_differently` (4.51% today). On every floored child no point is used and the cell note names the book year. Apple's used year is FY2023, since Apple tags no interest after it.
