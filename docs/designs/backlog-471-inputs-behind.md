# Backlog #471: the inputs behind an answer

Issue: https://github.com/sonderbot-ar/warren/issues/471 · Branch `backlog-471-inputs-behind` · Version v0.10.13 when merged.

## Problem

The owner asked (nov.19.2026) that every answer show a chart for each cell that feeds it: the cell's history over past years, the parts behind its changes, and the run's assumption beside them. The front-end team's mockup is approved (`docs/designs/f2-input-charts.md`, v0.10.12) and its build (F2 Step 4b) waits on one engine call. Today the app could put most of it together from `reported_series`, but it would then decide which history matches which assumption and compute growth contributions itself, which breaks the rule that every number comes from the engine. The run's own `history:*` rows hold only the three years the drivers use.

## What the call returns

`domains.analysis.inputs.inputs_behind(conn, run_id, outputs, years=5) -> InputsBehind`, read-only, point-in-time on the run's own `as_of` (every history value is one `reported_period` or `same_filing_annual_comparisons` gives on that date, so nothing filed after it is read).

- `outputs`: the output keys an answer shows, e.g. `[("revenue", "FY2026Q4"), …]` or `[("value_per_share", "-")]`. An unknown key is refused with code `output_not_in_run`.
- `years`: 3 to 10 fiscal years (filings go back to 2009); outside is refused with `years_out_of_range`. Default 5.

`InputsBehind` holds `run_id`, `ticker`, `as_of`, `years`, `outputs` (each `{name, period, value}`, the value the run stored, so the app draws the forecast from the same call) and `cells`: one cell per row name the outputs reach (the same set as `sources.reaches(output_trace(rows), key)`), in formula order (the outputs in the order asked, each formula's inputs in order, depth first). All rows of one name, whatever their periods, are one cell. A cell has:

1. **`rows`**: the reached rows of that name, each `{period, value, method_code, used}`. The row's `value` is the assumption itself (for a Σ ÷ Σ rule, the revenue-weighted figure, which is not the simple mean of the bars). `used` lists the history points the row was computed from, read from the row's stored sources (not recomputed): the `history:*` periods its `derived` source names (the `terminal_growth` input of the growth rows is not a history point and is skipped), the fiscal year of each current-year filing behind `revenue_growth`, the seed's own quarter, and, for a tax rate that left a year out, the `kept_years` of the run's `tax_rate_*_left_out` note (the stored source lists every year). A statutory tax rate uses no history point: `used` is empty and the cell carries `assumption_not_from_history`. `method_code` is one of a closed list (Step 1): `seed_quarter`, `seed_year_times_share`, `same_filing_average_fading`, `same_quarter_average`, `years_sum_ratio`, `years_sum_ratio_kept_years`, `statutory_tax_rate`, `year_end_average_ratio`, `owner_choice`, `single_value`.
2. **`history`**: a list of series, each `{measure, frequency, basis, points}`:
   - `basis` is `same_filing` (both years from one 10-K, as the growth assumption is computed) or `latest` (the latest value known on `as_of`, as `reported_series` gives). This is the gatekeeper's item 7 on #474.
   - `primary` is true on the series in the measure the assumption is computed on (for growth, the same-filing series); the others are context. A series has `fiscal_quarter` when it holds one fiscal quarter across years (the seed's and the quarterly margins', so a holiday quarter is compared only with holiday quarters), and its own `notes`: `reported_series`'s `series_mixes_meanings` and recast notes, so Exxon's ten-year charts across FY2016/FY2017 say their revenue changed meaning.
   - Windows: a year series holds the last `years` fiscal years ending at the latest quarter's fiscal year, so a year not yet filed (Apple's FY2026 on 2026-10-30) is the last point, with `missing: period_not_reported`. A quarterly series holds `years` × 4 quarters ending at the latest reported quarter. The seed's series hold `years` points per fiscal quarter, ending at the seed quarter itself. Points a row used are always included, whatever `years` is.
   - A point is `{period, fiscal_year, fiscal_period, period_end, value, used, parts, notes, missing}`. `used` is true when the cell's rows used this point, and only on the primary series. `notes` are the codes `reported_period` already gives on that ratio and its lines (`period_length_differs`, `tag_differs`, `mixed_vintage`, `uses_changed_line`, the one-basis, sign, part and meaning notes), so a chart can mark Apple's 53-week FY2023 (gatekeeper's item 6). `missing` is a code when the period has no value (`period_not_reported`, or the ratio's own missing code such as `base_not_positive`), so the screen can say why a point is absent.
   - A part is `{name, value, period, filing, derived, inputs, contribution, notes}`: a line the point's value is made of, with its filing (the #140 `Filing` shape) or, when derived, the filings it came from. A seed point has one part, the revenue line itself, so a derived fourth quarter (the year less nine months) carries `derived` and its filings, and the point the code `derived_from_other_periods`.
   - **`run_read_differently`**: a used point whose value differs from what the run itself read (its stored `history:*` rows, seed rows or growth filings) carries this note with both values and the run's reading-rules version. That happens on runs stored under older reading rules or before a filing changed a figure; the chart can then show both.
3. **`gap`**: a code when the cell has no history in this version: `owner_choice` (a row of `user_assumptions.csv`, e.g. terminal growth; its history is the choice itself) or `history_not_built` (a single value: risk-free rate, beta, ERP, cost of debt, shares, debt, cash, equity value, minority interest, roll years; Part 2, #476 below).

### History per cell (Part 1)

| Cell | Series (measure · frequency · basis) | Parts of each point |
|---|---|---|
| `revenue_seed` | `revenue` · quarter · latest: the same fiscal quarter in each of the last `years` years, one series per fiscal quarter the rows name | none (the point is a reported line, with its filing) |
| `revenue_growth` | `revenue_growth_yoy` · year · same_filing (primary, the assumption's measure); `revenue_growth_yoy` · year · latest; `revenue_growth_yoy` · quarter · latest (vs the same quarter a year earlier) | revenue this year and a year earlier; on the latest annual series also each fiscal quarter's contribution to the year's change, (Q − Q a year earlier) ÷ the year-earlier year, carrying the quarter's `period_length_differs` or `mixed_vintage`; when the quarters do not add up to the years as filed, a `not_in_quarters` residual part and the note `quarters_do_not_sum`, so the bars always add up to the year |
| `operating_margin` | `operating_margin` · quarter · latest, one series per fiscal quarter; `operating_margin` · year · latest | the facts of the EBIT the ratio used (operating income, or pretax income and interest with `ebit_from_pretax_plus_interest`, as Exxon's) and revenue; when EBIT is operating income, also cost of revenue and operating expenses if the period reports them |
| `tax_rate`, `debt_tax_rate` | `effective_tax_rate` · year · latest | income tax and pretax income |
| `da_pct` | `da_share` · year · latest | D&A and revenue |
| `capex_pct` | `capex_share` · year · latest | capex and revenue |
| `nwc_pct` | `operating_nwc_share` · year · latest | operating working capital (the run's own definition, `math_engine._operating_nwc`) and revenue; behind working capital its balance-sheet parts |

Every latest-basis ratio and growth point is the value `reported_period` computes (v0.9.6, checked equal to the valuations' own ratios). Two series are not: same-filing growth comes from `same_filing_annual_comparisons` (the pairs the growth driver averages), and working capital from the engine's own `_operating_nwc` on `load_history`. New numbers go through `financial_math.py`: a quarter's contribution (`fm.growth_contribution`, refused on a year-earlier total at or below zero), same-filing growth (`fm.growth`) and working capital over revenue (`fm.ratio`). `reported_period` gains a private `_shared` dict so the reads that depend only on the company and the date are made once per call (from about 17 s to 6 s for a full answer on Apple).

## Plan

**Step 0. Design doc and review (this doc).** Explainer, analyst, professor, and the front-end lead on *Product impact*. Exit: objections answered.

**Step 1. The call for the seed and the drivers.** `domains/analysis/inputs.py`: the dataclasses, `inputs_behind`, the method codes, the series above, the parts and notes. `fm.growth_contribution(current, prior, prior_year_total)`. Tests (synthetic database, as the reported-figures tests build it): a Q5 answer reaches exactly `revenue_seed` and `revenue_growth`; a `value_per_share` answer reaches every row name the trace gives, single values carry `history_not_built`, owner choices `owner_choice`; `used` equals the stored sources' periods; every point equals `reported_period` on the run's `as_of`; a fact filed after `as_of` never appears; a 53-week year carries `period_length_differs`; a missing year gives `period_not_reported`; same-filing and latest growth differ after a restatement and are both returned with their basis; `years` 3, 5 and 10 work and 2 and 11 are refused; Hypothesis: quarter contributions sum to the year's growth whenever the four quarters sum to the year. Exit: tests green.

**Step 2. Command line and the real check.** (Built in the same commit as Step 1.) `python -m domains.analysis inputs --run-id R --output revenue:FY2026Q4 … [--years N] [--json]`. Real data: on `AAPL_2026-10-30_1` the Q5 answer matches the mockup's figures (seed FY2025Q4 102,466 … FY2026Q3 109,417; growth 1.88% from FY2023–FY2025 −2.8%, 2.0%, 6.4%); on one stored run per company a `value_per_share` answer returns every cell with no error, and each driver row's `used` points recompute the row's value through `fm` to 1e-9 where the rule is a plain average or Σ/Σ of the points' parts. Exit: all eight companies pass; timing noted.

## Alternatives considered

- **The app builds it from `reported_series`.** Rejected in the issue: the app would choose the matching measure and compute contributions.
- **Store the history with each run.** Rejected: it would grow every run by ten years of lines for a view that reads only stored data and point-in-time queries; a read-only call is reproducible from the run's `as_of`.
- **Recompute `used` from the rules.** Rejected: the stored sources already name what each row used; recomputing could drift from older runs.
- **All single-value histories now.** Deferred to Part 2 (#476): each needs its own source (FRED by month, a beta per year-end window, the ERP's yearly estimate, debt and shares by quarter) and none is on the first screen (Q5). Q3 cards show their rows and a `history_not_built` code until then.

## Files to change

`domains/analysis/inputs.py` (new), `domains/analysis/financial_math.py` (`growth_contribution`), `domains/analysis/__main__.py` (`inputs` command), `tests/analysis/test_inputs.py` (new), `tests/analysis/test_financial_math.py`, `docs/versions.md`, `docs/build-plan.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q5 fully (the two cells of the first screen) and Q3, Q8 and every *Estimación* answer for the six drivers and the seed; single values (Q3's discount rate and bridge to equity) come back as cells with their rows and `history_not_built` until Part 2. Adds one library call and one command; nothing renamed or removed; no stored number changes. For the app: draw each `history` series, mark points with `used`, show `notes` and `missing` codes through the Spanish catalogue (new codes: `period_not_reported`, `derived_from_other_periods`, `quarters_do_not_sum`, `contribution_quarter_missing`, `counted_as_zero`, `run_read_differently`, `assumption_not_from_history`, `history_not_built`, `owner_choice`, the method codes, `output_not_in_run`, `years_out_of_range`, `run_not_found`; and `period_length_differs`, which now shows on chart points), and show the cell's `rows` as the assumption line and `outputs` as the forecast.

## Results

Real data, restored snapshot of nov.17 (schema 23), every company on 2026-10-30.

- **Apple's first screen matches the mockup.** On `AAPL_2026-10-30_1` the Q5 answer reaches exactly `revenue_seed` and `revenue_growth`. Seed points FY2025Q4 102,466, FY2026Q1 143,756, Q2 111,184, Q3 109,417 (millions), each with five years of its quarter; the fourth quarters carry `derived_from_other_periods`. Growth 1.88% from FY2023–FY2025 same-filing −2.80%, +2.02%, +6.43% (`period_length_differs` on FY2023 and FY2024, the 53-week year); FY2026 is the last point, `period_not_reported`. Quarterly growth for FY2026Q1–Q3: 15.65%, 16.60%, 16.36%.
- **Every driver row recomputes from its used points.** Fresh baseline runs on today's rules (`<T>_2026-10-30_2`, eight new runs stored for the check): on a `value_per_share` answer, 20 cells each and 49 rows per company checked (seed quarters equal the point; same-quarter margins and working capital are the mean of the used points; margin, D&A and capex Y3–Y5 equal Σ (point × revenue) ÷ Σ revenue; growth equals the mean of the same-filing points), all to 1e-9, at 3, 5 and 10 years, for all eight companies. Time per answer: 3.0–7.5 s at 5 years, 4.8–9.4 s at 10.
- **Older runs.** On the runs stored before reading rules were recorded (`<T>_2026-10-30_1`), working-capital points differ from what the run read for CAT, JNJ, KO, PG and XOM, and each carries `run_read_differently` (CAT FY2023: 14.7% in the run, 27.8% today, since #341 counts its current debt). Margins, D&A, capex, tax, growth and the seed agree on all eight.
- Tests: `tests/analysis/test_inputs.py`, 16 tests (one Hypothesis property).

## Review notes

Design review, nov.19.2026.

- **Explainer**: 16 points where it had to guess; taken: how rows of one name merge, the order of cells, the `terminal_growth` input skipped in `used`, growth `used` from the filings' fiscal years, owner-choice cells (rows, no history, `owner_choice`), same-filing points beyond three years (all pairs on the date, filtered to the window), `growth_contribution` on a non-positive total (refused), the forecast values. Left: the full list of a ratio's missing codes is the reported view's (`docs/product/brief.md` already words them).
- **Analyst**, four blockers, all taken: (1) a kept-years tax rate's `used` now comes from the run's note, not its sources; (2) series-level meaning and recast notes added; (3) margin parts are the facts of the EBIT actually used, and the lines behind operating income only when it is operating income; (4) a `not_in_quarters` residual and `quarters_do_not_sum` note, and a derived quarter's flags on its contribution. Suggestions taken: the "agree by construction" claim narrowed; length notes on contribution parts. Filed as #477: Caterpillar's working capital holds Cat Financial's receivables, a pooled reference per series, speed.
- **Professor**: PASS, no blockers. Taken: the primary series named; the residual; quarterly margins by fiscal quarter; a statutory tax rate's `used` empty with a note; the row's value is the pooled one (stated above). Idea for the app's glossary: same filing vs latest, contribution to growth, revenue-weighted average.
- **Front-end lead**: GO on *Product impact* after two blockers, both taken: Q4 seed points carry `derived` and their filings; the year series ends with the unfiled year as `period_not_reported`, so card C's "FY2026 entrará en el promedio" is driven by data. Also taken: forecast values in `outputs`, the window lengths, used points always included, `period_length_differs` added to the codes to word. Condition noted on #476: single-value history lands before the Q3 screen's mockup goes to the owner.
