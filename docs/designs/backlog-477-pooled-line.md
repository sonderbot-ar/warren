# Backlog #477 item 3: a reference line for each input chart

Issue: https://github.com/sonderbot-ar/warren/issues/477 (item 3 of 4) · Branch `backlog-477-pooled-line` · Version v0.10.16 when merged.

## Problem

The input charts (v0.10.12 mockup, v0.10.13 call) draw each driver's history with the points the run used marked, and the assumption as a line. For a margin, D&A, capex or tax rate, the assumption is Σ numerator ÷ Σ base over the years (revenue-weighted), not the simple mean of the bars. A student who averages the three marked bars by eye gets a different number from the line and has no way to see why (analyst and professor on #471). The app could compute the check itself, but the standing rule is that the engine computes every number, and the app would need each point's numerator and base, which it does not get.

Items 1, 2 and 4 of #477 stay open: Caterpillar's working-capital rule is a rule change that moves its value; speed is a profiling job; offering a fresh run for an old one is an app question.

## What changes

All additive; nothing renamed or removed; no stored number changes.

1. **Each ratio point carries its numerator and base.** `reported.Ratio` gains `numerator` and `base` (the summed facts `_ratio` already divides; `None` on a gap, on growth and on non-fraction ratios). `inputs.Point` gains `numerator` and `base` (from the ratio for margin, D&A, capex and tax points; operating working capital and revenue for the working-capital points; `None` elsewhere). The app can then write "Σ EBIT ÷ Σ revenue" with the real figures.
2. **Each primary series of a driver cell carries a `reference`.** `Series.reference: Reference | None`:
   - `method_code`: the rows' method (`years_sum_ratio`, `years_sum_ratio_kept_years`, `same_quarter_average`, `year_end_average_ratio`, `same_filing_average_fading`).
   - `how`: `pooled` (Σ numerator ÷ Σ base over the used points) or `mean` (the simple mean of the used points), from `method_code`.
   - `value`: the reference computed by `how` over the used points as this chart reads them today (`fm.pooled_ratio` or `fm.mean`).
   - `simple_mean`: the simple mean of the same points, always given, so the app can show "the plain average of the bars would be 30.1%; the line is 29.6% because larger years weigh more". Also `weights` (each point's share of the base sum, pooled only), `numerator_sum`, `base_sum`, and `numerator_code` and `base_code` (from `FORMULA_LINES`).
   - `periods`: the used points; `rows`: the row periods computed directly from them (growth: the first forecast row only, the start the later rows fade from to the terminal rate).
   - `notes` (`REFERENCE_NOTES`): `reference_point_missing` (a used point has no value today; `value` and `simple_mean` are then `None`, params `periods`); `reference_clipped` (a tax row equals `value` clipped to 0–50%; the cell carries `tax_rate_clipped`); `reference_differs_from_run` (params `run_value`, `value`, `rows`) when a row's stored value differs from `value` by more than 1e-9 relative otherwise, which happens on a run stored under older reading rules (its points already carry `run_read_differently`); and `reference_mixes_formulas` when the used points come from more than one formula.
   - `None` on context series (`primary` false), on the seed (the quarter itself), and on a statutory tax rate (no history behind it).
3. **Two pure functions in `financial_math.py`**: `pooled_ratio(numerators, bases)` = Σ numerators ÷ Σ bases (base sum must be positive, as `ratio`), and `mean(values)` (non-empty). Both plain Python floats, the sums as the engine's `_sum` does them, so a pooled reference equals the run's row to 1e-9 on today's rules.

## Plan

Tolerances: the tests compare a reference with its rows to 1e-12 on the synthetic company; the real check and the note use 1e-9 relative, as `run_read_differently` does.

**Step 0. This doc and its review.** Explainer, analyst, professor, and the front-end lead on *Product impact*. Exit: objections answered.

**Step 1. `fm.pooled_ratio` and `fm.mean`.** Tests in `tests/analysis/test_financial_math.py`, Hypothesis: one point gives that point's ratio; equal bases give the mean; the pooled value lies between the smallest and largest point ratio; scaling every base and numerator by the same factor leaves it unchanged; a non-positive base sum and an empty list are refused. Exit: tests green.

**Step 2. Numerator and base on the ratio and the point; the reference on each primary series.** `reported.py`, `inputs.py`. Tests in `tests/analysis/test_inputs.py` (synthetic company): on a fresh run every primary driver series' `reference.value` equals each of its `rows`' stored values to 1e-12 and carries no note; margin Y3–Y5, D&A, capex and tax are `pooled`, quarterly margins, working capital and growth `mean`; `numerator ÷ base` equals each ratio point's value; a pooled reference differs from the simple mean when the years' revenues differ (a company whose margin and revenue both grow); a run whose stored history was changed gets `reference_differs_from_run`; a used point removed gets `reference_point_missing`; context series and the seed have no reference; a statutory tax rate has none; a kept-years tax rate pools only the kept years. Exit: tests green.

**Step 3. Real check.** Restored snapshot of nov.19 (after `reproduce`-style checks the step relies on: the inputs call reads stored runs only). Fresh runs on today's rules for every company on 2026-10-30 (`AAPL`, `MSFT`, `WMT` `_2` built for the check; `CAT_3`, `JNJ_2`, `KO_2`, `PG_2`, `XOM_2` already stored under v11) and, for the tax paths the analyst named, `CAT_2019-10-23`, `XOM_2019-08-19`, `KO_2019-07-23` (own rates of 138%, −5%, 82% in some years). A `value_per_share` answer: every primary reference matches its rows to 1e-9 with no note; on older runs, notes only where points carry `run_read_differently`. Record pooled against simple mean in Results. Exit: all pass.

## Alternatives considered

- **The app computes the check.** Rejected: the engine computes every number (standing rule), and the app would have to know which rows pool and which average.
- **Only `numerator` and `base` on points, no reference.** Rejected: the app would still sum and divide.
- **Compare against the run's own `history:*` rows instead of today's points.** Rejected for the line: the chart draws today's points, so the line's check must use the same points; the comparison with the run is the `reference_differs_from_run` note.

## Files

`domains/analysis/financial_math.py`, `domains/analysis/reported.py`, `domains/analysis/inputs.py`, `tests/analysis/test_financial_math.py`, `tests/analysis/test_inputs.py`, `docs/team-sync.md`, `docs/versions.md`.

## Product impact (after the front-end lead's review)

Serves brief Q5 (the growth card) and Q3, Q8 and every *Estimación* card that shows a margin, D&A, capex, tax or working-capital chart: the assumption line can be labelled with how it was computed and checked against the bars. Adds `Ratio.numerator`, `Ratio.base`, `Point.numerator`, `Point.base`, `Point.formula_id`, `Series.reference` (`Reference`); new codes for the app to word: the four `REFERENCE_NOTES`, the `how` values `pooled` and `mean`, and the line codes of `FORMULA_LINES` (`operating_income`, `pretax_income_plus_interest`, `capex`, `d_and_a`, `income_tax`, `pretax_income`, `pretax_income_by_region`, `net_income_plus_tax`, `revenue`). The professor's wording advice for the app: say "ponderado por ingresos" or "ponderado por utilidad antes de impuestos" (from `base_code`), not "pooled". Nothing renamed or removed.

## Reviews

- **Explainer**: 20 gaps; the ones that changed the doc: tolerances stated once; `simple_mean` is `None` with `value` when a point is missing; `rows` defined by the rows' own `used` (quarterly margins, growth's held rows); the method-to-`how` table is `POOLED_METHODS` and `MEAN_METHODS`; tax's base named; kept years named. The rest (brief references, which reference the card reads: the primary series the card already draws) need no change.
- **Analyst**: GO after two blockers, both taken: Step 3 names its runs and builds fresh ones; the 2019 tax cases are checked. Suggestions taken: clipping has its own code (`reference_clipped`), growth's `rows` are all the held rows (four on Exxon), a note when the used points mix formulas, sums in fiscal order (the points are in order). Not taken here, filed as a backlog issue: a note when an older run pooled years today's rules would leave out (Exxon 2019-08-19 run 1 pools FY2016–FY2018 to 13.8%; today it keeps FY2018 only, 30.8%), which is about the run, not the line.
- **Professor**: PASS (ratio of means, Cochran 1977 ch. 6; long-run effective tax rate, Dyreng, Hanlon and Maydew 2008). Taken: the weighting identity as a Hypothesis property; `base_code`; per-point `weights`. The wording idea is in *Product impact*.
- **Front-end lead**: GO after two blockers, both taken: `numerator_sum` and `base_sum` on the reference; a what-if's or owner's own value gets no reference row and no "older rules" note. Also taken: line codes, units, growth's rows, `simple_mean` for `mean`.

## Results

Real data, restored snapshot of nov.19 (schema 23). A `value_per_share` answer on 11 fresh runs: every primary reference equals its rows to 1e-9 with no note, including Exxon 2019 (tax kept to FY2018 alone, 30.80%) and Caterpillar 2019. Pooled against the bars' plain average, year series:

| Run | Operating margin | Tax rate | Capex |
|---|---|---|---|
| AAPL 2026-10-30 | 31.13% vs 31.10% | 18.17% vs 18.14% | 2.78% vs 2.78% |
| MSFT 2026-10-30 | 45.79% vs 45.68% | 18.53% vs 18.42% | 26.20% vs 25.33% |
| WMT 2026-10-30 | 4.22% vs 4.22% | 24.38% vs 24.45% | 3.48% vs 3.47% |
| CAT 2026-10-30 | 18.65% vs 18.67% | 21.54% vs 21.65% | 3.21% vs 3.21% |
| JNJ 2026-10-30 | 24.92% vs 24.62% | 15.75% vs 14.99% | 5.15% vs 5.15% |
| KO 2026-10-30 | 24.91% vs 24.89% | 17.95% vs 17.96% | 4.28% vs 4.28% |
| PG 2026-10-30 | 23.00% vs 23.01% | 20.44% vs 20.43% | 4.51% vs 4.50% |
| XOM 2026-10-30 | 14.16% vs 14.14% | 28.51% vs 28.45% | 7.27% vs 7.28% |
| CAT 2019-10-23 | 10.03% vs 9.33% | 21.71% vs 21.71% | 2.37% vs 2.39% |
| XOM 2019-08-19 | 8.29% vs 7.89% | 30.80% (one year) | 7.13% vs 7.19% |
| KO 2019-07-23 | 22.87% vs 23.15% | 19.47% vs 19.47% | 4.84% vs 4.79% |

Older runs: `CAT_2026-10-30_1`, `KO_2026-10-30_1`, `XOM_2019-08-19_1` get `reference_differs_from_run` on working capital only, and `CAT_2019-10-23_1` also on its fourth-quarter margin, each where the points already carry `run_read_differently` (CAT's working capital: 16.2% in the run, 27.5% today, since #341). Time per answer: 3.0–9.9 s, as before (#477 item 2). Tests: 9 new in `tests/analysis/test_inputs.py`, 3 in `test_financial_math.py`, 6 Hypothesis properties.
