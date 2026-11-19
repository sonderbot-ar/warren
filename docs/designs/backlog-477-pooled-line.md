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
   - `mean`: the simple mean of the same points, always given, so the app can show "the plain average of the bars would be 30.1%; the line is 29.6% because larger years weigh more".
   - `periods`: the used points; `rows`: the row periods computed directly from them (growth: the first forecast row only, the start the later rows fade from to the terminal rate).
   - `notes`: `reference_point_missing` (a used point has no value today; `value` and `mean` are then `None`, params `periods`), and `reference_differs_from_run` (params `run_value`, `value`, `rows`) when a row's stored value differs from `value` by more than 1e-9 relative, which happens on a run stored under older reading rules (its points already carry `run_read_differently`) or when the tax rate was clipped to 0–50% (the cell carries `tax_rate_clipped`).
   - `None` on context series (`primary` false), on the seed (the quarter itself), and on a statutory tax rate (no history behind it).
3. **Two pure functions in `financial_math.py`**: `pooled_ratio(numerators, bases)` = Σ numerators ÷ Σ bases (base sum must be positive, as `ratio`), and `mean(values)` (non-empty). Both plain Python floats, the sums as the engine's `_sum` does them, so a pooled reference equals the run's row to 1e-9 on today's rules.

## Plan

**Step 0. This doc and its review.** Explainer, analyst, professor, and the front-end lead on *Product impact*. Exit: objections answered.

**Step 1. `fm.pooled_ratio` and `fm.mean`.** Tests in `tests/analysis/test_financial_math.py`, Hypothesis: one point gives that point's ratio; equal bases give the mean; the pooled value lies between the smallest and largest point ratio; scaling every base and numerator by the same factor leaves it unchanged; a non-positive base sum and an empty list are refused. Exit: tests green.

**Step 2. Numerator and base on the ratio and the point; the reference on each primary series.** `reported.py`, `inputs.py`. Tests in `tests/analysis/test_inputs.py` (synthetic company): on a fresh run every primary driver series' `reference.value` equals each of its `rows`' stored values to 1e-12 and carries no note; margin Y3–Y5, D&A, capex and tax are `pooled`, quarterly margins, working capital and growth `mean`; `numerator ÷ base` equals each ratio point's value; a pooled reference differs from the simple mean when the years' revenues differ (a company whose margin and revenue both grow); a run whose stored history was changed gets `reference_differs_from_run`; a used point removed gets `reference_point_missing`; context series and the seed have no reference; a statutory tax rate has none; a kept-years tax rate pools only the kept years. Exit: tests green.

**Step 3. Real check.** Restored snapshot of nov.19. On the eight fresh runs `<T>_2026-10-30_2` (today's rules), a `value_per_share` answer: every primary reference matches its rows to 1e-9 with no note; on the older `<T>_2026-10-30_1` runs, references differ only where points carry `run_read_differently` or the tax rate was clipped. Record pooled against simple mean per company in Results. Exit: all eight pass.

## Alternatives considered

- **The app computes the check.** Rejected: the engine computes every number (standing rule), and the app would have to know which rows pool and which average.
- **Only `numerator` and `base` on points, no reference.** Rejected: the app would still sum and divide.
- **Compare against the run's own `history:*` rows instead of today's points.** Rejected for the line: the chart draws today's points, so the line's check must use the same points; the comparison with the run is the `reference_differs_from_run` note.

## Files

`domains/analysis/financial_math.py`, `domains/analysis/reported.py`, `domains/analysis/inputs.py`, `tests/analysis/test_financial_math.py`, `tests/analysis/test_inputs.py`, `docs/team-sync.md`, `docs/versions.md`.

## Product impact

Serves brief Q5 (the growth card) and Q3, Q8 and every *Estimación* card that shows a margin, D&A, capex, tax or working-capital chart: the assumption line can be labelled with how it was computed and checked against the bars. Adds `Ratio.numerator`, `Ratio.base`, `Point.numerator`, `Point.base`, `Series.reference`; new codes for the app to word: `reference_point_missing`, `reference_differs_from_run`, and `how` values `pooled` and `mean`. Nothing renamed or removed.
