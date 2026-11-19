# Backlog #471: the inputs behind an answer

Issue: https://github.com/sonderbot-ar/warren/issues/471 · Branch `backlog-471-inputs-behind` · Version v0.10.13 when merged.

## Problem

The owner asked (nov.19.2026) that every answer show a chart for each cell that feeds it: the cell's history over past years, the parts behind its changes, and the run's assumption beside them. The front-end team's mockup is approved (`docs/designs/f2-input-charts.md`, v0.10.12) and its build (F2 Step 4b) waits on one engine call. Today the app could put most of it together from `reported_series`, but it would then decide which history matches which assumption and compute growth contributions itself, which breaks the rule that every number comes from the engine. The run's own `history:*` rows hold only the three years the drivers use.

## What the call returns

`domains.analysis.inputs.inputs_behind(conn, run_id, outputs, years=5) -> InputsBehind`, read-only, point-in-time on the run's own `as_of` (every history value is one `reported_period` or `same_filing_annual_comparisons` gives on that date, so nothing filed after it is read).

- `outputs`: the output keys an answer shows, e.g. `[("revenue", "FY2026Q4"), …]` or `[("value_per_share", "-")]`. An unknown key is refused with code `output_not_in_run`.
- `years`: 3 to 10 fiscal years (filings go back to 2009); outside is refused with `years_out_of_range`. Default 5.

`InputsBehind` holds `run_id`, `ticker`, `as_of`, `years`, `outputs` and `cells`, one cell per row name the outputs reach (`sources.reaches(output_trace(rows), key)`), in formula order (the order `output_trace` first names them). A cell has:

1. **`rows`**: the reached rows of that name, each `{period, value, method_code, used}`. `used` lists the history points the row was computed from, read from the row's stored sources (not recomputed): the `history:*` periods its `derived` source names, the fiscal years of the current-year filings behind `revenue_growth`, and the seed's own quarter. `method_code` is one of a closed list (Step 1): `seed_quarter`, `seed_year_times_share`, `same_filing_average_fading`, `same_quarter_average`, `years_sum_ratio`, `years_sum_ratio_kept_years`, `statutory_tax_rate`, `year_end_average_ratio`, `owner_choice`, `single_value`.
2. **`history`**: a list of series, each `{measure, frequency, basis, points}`:
   - `basis` is `same_filing` (both years from one 10-K, as the growth assumption is computed) or `latest` (the latest value known on `as_of`, as `reported_series` gives). This is the gatekeeper's item 7 on #474.
   - A point is `{period, fiscal_year, fiscal_period, period_end, value, used, parts, notes, missing}`. `used` is true when the cell's rows used this point. `notes` are the codes `reported_period` already gives on that ratio and its lines (`period_length_differs`, `tag_differs`, `mixed_vintage`, `uses_changed_line`, the one-basis, sign, part and meaning notes), so a chart can mark Apple's 53-week FY2023 (gatekeeper's item 6). `missing` is a code when the period has no value (`period_not_reported`, or the ratio's own missing code such as `base_not_positive`), so the screen can say why a point is absent.
   - A part is `{name, value, period, filing, derived, inputs}`: a line the point's value is made of, with its filing (the #140 `Filing` shape) or, when derived, the filings it came from.
3. **`gap`**: a code when the cell has no history in this version: `owner_choice` (a row of `user_assumptions.csv`, e.g. terminal growth; its history is the choice itself) or `history_not_built` (a single value: risk-free rate, beta, ERP, cost of debt, shares, debt, cash, equity value, minority interest, roll years; Part 2, #476 below).

### History per cell (Part 1)

| Cell | Series (measure · frequency · basis) | Parts of each point |
|---|---|---|
| `revenue_seed` | `revenue` · quarter · latest: the same fiscal quarter in each of the last `years` years, one series per fiscal quarter the rows name | none (the point is a reported line, with its filing) |
| `revenue_growth` | `revenue_growth_yoy` · year · same_filing (the assumption's measure); `revenue_growth_yoy` · year · latest; `revenue_growth_yoy` · quarter · latest (vs the same quarter a year earlier) | revenue this year and a year earlier; on the latest annual series also each fiscal quarter's contribution to the year's change, (Q − Q a year earlier) ÷ the year-earlier year |
| `operating_margin` | `operating_margin` · quarter · latest; `operating_margin` · year · latest | EBIT and revenue; behind EBIT, cost of revenue and the other operating lines the period reports |
| `tax_rate`, `debt_tax_rate` | `effective_tax_rate` · year · latest | income tax and pretax income |
| `da_pct` | `da_share` · year · latest | D&A and revenue |
| `capex_pct` | `capex_share` · year · latest | capex and revenue |
| `nwc_pct` | `operating_nwc_share` · year · latest | operating working capital (the run's own definition, `math_engine._operating_nwc`) and revenue; behind working capital its balance-sheet parts |

Every ratio and growth point is the value `reported_period` already computes (v0.9.6, checked equal to the valuations' own ratios), so the history and the run agree by construction. Two new numbers are computed, both in `financial_math.py`: a quarter's contribution to annual growth (`fm.growth_contribution`) and operating working capital over revenue (`fm.ratio`, through the engine's `_operating_nwc`).

## Plan

**Step 0. Design doc and review (this doc).** Explainer, analyst, professor, and the front-end lead on *Product impact*. Exit: objections answered.

**Step 1. The call for the seed and the drivers.** `domains/analysis/inputs.py`: the dataclasses, `inputs_behind`, the method codes, the series above, the parts and notes. `fm.growth_contribution(current, prior, prior_year_total)`. Tests (synthetic database, as the reported-figures tests build it): a Q5 answer reaches exactly `revenue_seed` and `revenue_growth`; a `value_per_share` answer reaches every row name the trace gives, single values carry `history_not_built`, owner choices `owner_choice`; `used` equals the stored sources' periods; every point equals `reported_period` on the run's `as_of`; a fact filed after `as_of` never appears; a 53-week year carries `period_length_differs`; a missing year gives `period_not_reported`; same-filing and latest growth differ after a restatement and are both returned with their basis; `years` 3, 5 and 10 work and 2 and 11 are refused; Hypothesis: quarter contributions sum to the year's growth whenever the four quarters sum to the year. Exit: tests green.

**Step 2. Command line and the real check.** `python -m domains.analysis inputs --run-id R --output revenue:FY2026Q4 … [--years N] [--json]`. Real data: on `AAPL_2026-10-30_1` the Q5 answer matches the mockup's figures (seed FY2025Q4 102,466 … FY2026Q3 109,417; growth 1.88% from FY2023–FY2025 −2.8%, 2.0%, 6.4%); on one stored run per company a `value_per_share` answer returns every cell with no error, and each driver row's `used` points recompute the row's value through `fm` to 1e-9 where the rule is a plain average or Σ/Σ of the points' parts. Exit: all eight companies pass; timing noted.

## Alternatives considered

- **The app builds it from `reported_series`.** Rejected in the issue: the app would choose the matching measure and compute contributions.
- **Store the history with each run.** Rejected: it would grow every run by ten years of lines for a view that reads only stored data and point-in-time queries; a read-only call is reproducible from the run's `as_of`.
- **Recompute `used` from the rules.** Rejected: the stored sources already name what each row used; recomputing could drift from older runs.
- **All single-value histories now.** Deferred to Part 2 (#476): each needs its own source (FRED by month, a beta per year-end window, the ERP's yearly estimate, debt and shares by quarter) and none is on the first screen (Q5). Q3 cards show their rows and a `history_not_built` code until then.

## Files to change

`domains/analysis/inputs.py` (new), `domains/analysis/financial_math.py` (`growth_contribution`), `domains/analysis/__main__.py` (`inputs` command), `tests/analysis/test_inputs.py` (new), `tests/analysis/test_financial_math.py`, `docs/versions.md`, `docs/build-plan.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q5 fully (the two cells of the first screen) and Q3, Q8 and every *Estimación* answer for the six drivers and the seed; single values (Q3's discount rate and bridge to equity) come back as cells with their rows and `history_not_built` until Part 2. Adds one library call and one command; nothing renamed or removed; no stored number changes. For the app: draw each `history` series, mark points with `used`, show `notes` and `missing` codes through the Spanish catalogue (new codes: `period_not_reported`, `history_not_built`, `owner_choice`, the method codes, `output_not_in_run`, `years_out_of_range`), and show the cell's `rows` as the assumption line.

## Review notes

(Filled after the design review.)
