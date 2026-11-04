# Backlog #145: a company's track record

Issue: https://github.com/sonderbot-ar/warren/issues/145 · Branch `backlog-145-track-record` · Version v0.9.14 when merged.

## Problem

The front-end team's request R4 (brief question 6, `docs/product/brief.md` §5: "¿Qué tan bien ha pronosticado Warren a Procter & Gamble en el pasado?"). The brief asks, for one company: past forecasts beside the first-reported actuals, quarter by quarter, the error, how often the range held the actual, and the same for a simple benchmark (last year's quarter carried forward), with the company's own miscalibration shown, not pooled away. Today every stored history pools companies: M3 and M8 report all cases together (`domains/evaluation/report.py`, `backtest_report.py`), M9 reports coverage pooled with a per-company table (`ranges_report.py`), and v0.9.8's `run_ranges` gives a company's coverage but not its forecasts, misses or the benchmark.

## What the history is

The track record is M9's monthly origins (`forecast_origins`, `baseline_errors`, migration 0017): the baseline run as of the 1st of every month since 2019-04 for every company, each forecast quarter 1–4 scored against the actual as first reported, with the date that actual was filed. That is the systematic history (about 30 target quarters and 115 quarter-and-horizon pairs per company). The case batches of M3 and M8 are not used here; see Alternatives.

**One row per target quarter and horizon, not per origin.** Monthly origins repeat a forecast until a new filing lands, so one target quarter is scored at the same horizon by up to four origins (AAPL FY2023Q1 at h1 has four). On the restored data every such group holds one forecast: 920 of 920 revenue groups and 920 of 920 EBIT groups have a single distinct forecast, one `actual_filed_at` and one benchmark (Step 3; the analyst's queries agree). So a row is (target quarter, horizon), taken from the **earliest** origin in its group: the first date Warren made that forecast (`made_on`, that origin's as-of, the first of a month). `n_origins` says how many monthly origins repeated it. The range is the one exception: it is taken from the earliest origin of the group that M9's rolling test scored (dated 2021-01-01 or later), so 28 groups whose first origin falls in M9's warm-up still get their range (analyst); `ranges.<pool>.made_on` names that origin. This is what a student reads as "Warren's forecast for P&G's Q3, made two quarters ahead", and it stops the summaries from counting one miss three times (the #144 analyst's finding).

## What changes

A new call `domains.evaluation.track_record.track_record(conn, ticker, as_of=None, n=10_000) -> TrackRecord`, and a command `python -m domains.evaluation track-record --ticker T [--as-of D] [--json]`. Without a date it uses `shared_kernel.calendar.last_ended_day(now)`, `now` the current UTC time unless passed (as v0.9.7's commands do), and says so (`as_of_default`). `n` is M9's resample count per range. As of D:

1. **Rows.** For each (target quarter, horizon 1–4) of the company whose earliest origin is dated before D and whose revenue and EBIT actuals were both filed on or before D (`actual_filed_at`, the later of the two, as M9's `load_pairs`), with both errors `ok`:
   - `period`, `period_end`, `horizon`, `made_on` (the earliest origin's date), `origin_id`, `run_id`, `n_origins` (origins dated before D in the group);
   - per item (`revenue`, `ebit`): `forecast` and `actual` (first reported) in money, `filed_at`, and the miss as M3 scores it (`harness.score`), named as v0.9.7's `hindsight` names it (product-lead): `miss` is absolute, `signed_miss` is (forecast − actual) / scale, so **positive means Warren forecast too high**, and `miss_unit` says the scale: `fraction_of_actual` for revenue, `fraction_of_actual_revenue` for EBIT (margin points, scaled by the first-reported revenue of the same quarter). This is not M9's stored error, which is ln(actual / forecast) with the opposite sign (`ranges.py:100`); a test guards the two apart (analyst). An ok M9 row always has a positive actual revenue (its log exists), so `score` never meets a zero scale;
   - the **benchmark**, M3's seasonal random walk (`naive_srw`): the same quarter a year earlier as known on `made_on`, read from the origin run's own stored history rows (`history:revenue`, `history:ebit` at period − 4, `runs.load_assumptions`), exactly as `harness.evaluate_case` builds it; `benchmark_forecast`, `benchmark_miss`, `benchmark_signed_miss`; `closer`: `warren`, `benchmark` or `tie` (equal absolute misses to 1e-12). A run without that history row gives `benchmark_missing` `no_benchmark` and `closer` None (none on the real data: 0 of 5,410 rows, analyst);
   - the **range** per pool (`pooled`, `own`): M9's p10–p90 in money, as built on its origin's date from the misses known that day and seeded by the origin id (`run_ranges.scored_origin_rows`). Each gives `made_on`, `p10`, `p90` and `held`: `inside`, `below` (the actual fell below p10: the range sat too high) or `above` (ends count as inside, as M8). A group with no origin from 2021-01-01 on is `warm_up`; a pool short of misses that day (under 20 pooled, 12 own, M9's `MIN_ERRORS`) is `no_history`;
   - `basis_change`: the v0.9.7 detector (`run_ranges.basis_flags`, filings public by D) flags the quarter, for either item, on any origin of the group (JNJ after Kenvue, KO 2019, XOM 2019). The row stays in: until #162, M9 counts it as a miss, and the student sees why.
2. **Summaries** per item, per horizon 1–4 and over all horizons (`horizon` None):
   - `n_rows` and `n_quarters` (distinct target quarters; every minimum counts these, professor B2), `miss_unit`, Warren's and the benchmark's median and mean absolute miss, and `skill`, 1 − mean miss ÷ benchmark mean miss (relative MAE, Davydenko & Fildes 2013; above 0 beats the benchmark);
   - **the test against the benchmark** (professor B1, analyst B1). d is Warren's absolute miss minus the benchmark's. Over all horizons, one target quarter's four horizons share one actual, so d is averaged per target quarter and the sign test (`backtest.sign_test`, M8's, exact two-sided) runs on those, one per quarter, as M8 tests per case (note `tested_per_quarter`). On rows instead, CAT revenue would read "benchmark better" at p = 8e-6 where per quarter it is p = 0.36 (analyst's recomputation). At horizon 1 the test runs on the rows (one per quarter). At horizons 2–4, consecutive forecasts overlap (Diebold & Mariano 1995; Harvey, Leybourne & Newbold 1997), so wins and p are shown but there is no verdict (note `overlapping_horizon`). `verdict`: `warren_better` or `benchmark_better` when p < 0.05, else `not_shown` (never "the same": with about 30 quarters the test has little power); None when every difference is a tie; `few_quarters` (params `n_quarters`, `min_quarters` 12) under 12 distinct quarters, and then no verdict;
   - **the range's record** per pool, on the deduplicated rows: `inside`, `below`, `above`, `n_rows`, `n_quarters`, `n_clusters`, `share`, the 90% cluster bootstrap by calendar quarter (`ranges_report.cluster_bootstrap`, M9's), `target` 0.80, `acceptable` [0.65, 0.95], `verdict` (`held`, `too_narrow`, `too_wide`; `run_ranges.verdict`), `target_in_interval`, and `width` (#144's: median (p90 − p10) ÷ p50, EBIT over the revenue p50), so a 100% that comes from a very wide range shows as such (product-lead); `few_scored` under 12 distinct quarters; `all_inside` when every actual was inside (the interval collapses to 100–100% and says nothing);
   - beside it, `others_share`: the same deduplicated share over the **other** seven companies cut at D (leave-one-out, professor), and `differs_from_others` when it lies outside the company's interval, so the screen can say "for P&G the range held more often than for the others";
   - `share_by_origin`: the company's share counted per monthly origin, as M9 and v0.9.8's `run_ranges` count it, so the app can explain why Q5's screen and Q6's differ for the same date (product-lead);
   - `basis_changes` per summary and, per range cell, `basis_changes` and `basis_changes_outside`.
   **The headline** is `headline`: `{horizon: None, pool: "pooled"}`, all horizons tested per quarter, with the pooled range, the range the forecast screen (Q5, v0.9.8) leads with; the other cells are detail (product-lead; professor's multiple-testing idea: two verdicts per company and item, not ten).
3. **Notes.** `deduplicated` (params `rows`, `origins`), `benchmark_is_srw`, `baseline_only` (the range and misses are the baseline's, not the news shocks'), `cases_not_included` (see Alternatives), `headline`, `code_differs` (when the company's origins were built with more than one code version), and `origins_failed` (params `n`, `first`, `last`, `reasons`) when some monthly forecasts could not be made: XOM's ten 2026 origins failed because its filings stop on 2026-08-03 (#126), so its record is shorter and the screen should say why (analyst).

Everything is point in time: rows need origins dated before D and both actuals filed by D; the benchmark is the origin run's own history as known on its date; the ranges are built from misses filed by the origin's date; the basis flags read filings public by D. Nothing is written. A ticker that has not been ingested raises `EvaluationError`; a company with no scored row returns empty rows and the coded gap `no_track_record`.

All money is raw, in the company's currency (`currency`, `montecarlo._currency`; Decision 11). Misses are fractions. Gaps and notes are coded (`reported.Coded`: `code`, `params`, `text` in English), never raised.

## Steps

- **Step 0.** This design doc and its review.
- **Step 1.** `domains/evaluation/track_record.py`: `track_record`, `TrackRecord.to_dict`, helpers `rows_for`, `benchmark`, `summaries`, `range_cells`. Tests (`tests/evaluation/test_track_record.py`, synthetic origins in a migrated database as `test_run_ranges.py` builds them, plus stored runs for the history rows): three origins repeating one forecast give one row with `n_origins` 3 and `made_on` the earliest; an origin dated D is not used and one dated D − 1 is; an actual filed D + 1 is not used; revenue filed by D but EBIT after D is not used; the miss equals `harness.score`; the benchmark equals the run's `history:` row for period − 4 and its miss `harness.score` on it; `closer` on a tie; wins + losses + ties = n; the sign-test verdict at p just below and above 0.05; `few_quarters` at 11 and not 12; `held` inside at p10 exactly; `warm_up` before 2021; the range's p10/p90 equal `run_ranges.scored_origin_rows`'s for the same origin; `all_companies_share` and `differs_from_all`; a flagged basis change counted; the same call twice gives the same dict; `to_dict` round-trips through `json`; an unknown ticker raises; a company with no rows gives `no_track_record`. Exit: green.
- **Step 2.** The command: per item, a table of quarters (period, horizon, made on, forecast, actual, miss, benchmark miss, range held), then the summaries and the notes; `--json` prints `to_dict` only. Tests in `tests/evaluation/test_cli.py`. Exit: green; ruff clean.
- **Step 3.** Real data on the restored snapshot: the one-forecast-per-group check (920 of 920); for every company as of 2026-11-02, the call's range rows equal M9's stored `ranges_2026-11-02_1` rows for the same origins; the benchmark equals the stored `naive_srw` rows of the one case whose ticker and date are also an origin's (KO_2021-11-01; no case run id is an origin run id, analyst B3); the eight companies' summaries written below with the timing. Exit: equalities hold.

**Exit criterion:** all tests pass; Step 3's equalities hold; `docs/team-sync.md` names the call and its fields; brief Q6's "Hoy" line updated.

## Alternatives considered

- **Use the case batches too.** Left out for now. The M3 and M8 cases (three or four per company) were chosen around events, so they are not a fair sample of how Warren does on a company, and the M8 batch (`eval_2026-11-02_1`) left `actual_filed_at` empty, so a point-in-time cut would need its scoring recomputed. The M10 batches do fill it (852 of 872 and 916 of 936 baseline rows, analyst) and their dates are chosen by rule, so they are the right addition, but M10 is not merged and its batches may still change before 2026-11-16. Filed as #189, for when M10 merges.
- **One row per origin, as M9 scores.** Rejected: it counts one forecast up to three times and makes a company's record look surer than it is.
- **The latest origin in each group instead of the earliest.** Same forecast, but a later origin's range knows more misses. The earliest is the first time Warren said it, which is the honest "what did we say then".
- **Store the track record.** Rejected: it changes whenever new actuals are scored. The call is deterministic for a date and the stored data; `errors_sha256` identifies the misses known on D, but the answer also reads the origin runs' history rows and the filings behind the basis flags, so it is not a full cache key (explainer).

## Files to change

New: `domains/evaluation/track_record.py`, `tests/evaluation/test_track_record.py`. Changed: `domains/evaluation/__main__.py` (`track-record`), `tests/evaluation/test_cli.py`; at merge `docs/versions.md`, `docs/team-sync.md`, `docs/product/brief.md` (Q6 "Hoy"), this doc's results.

## Product impact

Serves brief question 6 and design principle 4 (show the uncertainty measured). Q6's "Hoy" changes from "En parte … Request R4 (#145)" to "Sí" for the monthly history. No existing output, name or field changes; no migration.

Fields of `to_dict`:

- top: `ticker`, `as_of`, `as_of_default` (true when the date was chosen as the last ended day), `currency`, `errors_sha256`, `headline` (`{horizon: null, pool: "pooled"}`), `rows[]`, `summaries[]`, `notes[]`, `missing`;
- a row: `period`, `period_end`, `horizon`, `made_on`, `origin_id`, `run_id`, `n_origins`, `basis_change`, `items` {`revenue`, `ebit`}, each with `forecast`, `actual` (money), `filed_at`, `miss` (absolute), `signed_miss` (positive: Warren too high), `miss_unit` (`fraction_of_actual`, `fraction_of_actual_revenue`), `benchmark_forecast` (money), `benchmark_miss`, `benchmark_signed_miss`, `benchmark_missing`, `closer`, `ranges` {`pooled`, `own`} each `made_on`, `p10`, `p90` (money), `held`, `missing`;
- a summary: `item`, `horizon` (1–4, or null for all), `miss_unit`, `n_rows`, `n_quarters`, `median_miss`, `mean_miss`, `benchmark_median_miss`, `benchmark_mean_miss`, `skill`, `wins`, `losses`, `ties`, `sign_p`, `verdict`, `basis_changes`, `missing`, `notes[]`, `ranges` {`pooled`, `own`} each `inside`, `below`, `above`, `n_rows`, `n_quarters`, `n_clusters`, `share`, `interval`, `target`, `acceptable`, `verdict`, `target_in_interval`, `width`, `others_share`, `differs_from_others`, `share_by_origin`, `basis_changes`, `basis_changes_outside`, `missing`, `notes[]`;
- misses and shares are fractions (0.05 is 5%); money is whole currency units;
- codes the app needs words for: `no_track_record`, `few_quarters`, `few_scored`, `warm_up`, `no_history`, `no_benchmark`, `all_inside`; verdicts `warren_better`, `benchmark_better`, `not_shown`, `held`, `too_narrow`, `too_wide`; `inside`, `below`, `above`; `warren`, `benchmark`, `tie`; notes `deduplicated`, `benchmark_is_srw`, `baseline_only`, `cases_not_included`, `headline`, `horizons_pooled`, `tested_per_quarter`, `overlapping_horizon`, `code_differs`, `origins_failed`.

A call takes 8–12 seconds on the restored data (most of it building every company's past ranges and the basis check), so the app needs a loading state; the answer may be kept per ticker and date until new misses are scored.

Q6's "Hoy" line becomes: "Sí (monthly history since 2019; the case batches join when M10 merges)".

## Design review (nov.04.2026)

Explainer, analyst, professor and the front-end product-lead, in parallel. Analyst NO-GO (3 blockers), professor NO-GO (2), product-lead 4 blockers, explainer 6 gaps; all taken above.

- **Analyst.** (1) The all-horizons sign test counted one actual up to four times and flipped verdicts (CAT, JNJ, PG revenue, WMT EBIT): now one averaged difference per target quarter, no verdict at h ≥ 2. (2) `eval_results` does have `actual_filed_at`, filled by the M10 batches: the reason for leaving cases out is restated. (3) Step 3's benchmark check matched nothing by run id: now by ticker and date, one case. Ideas taken: up to four origins per group; the range from the group's first origin in M9's test; `origins_failed` for XOM; basis flags over the whole group; a test that the signed miss and M9's ln error have opposite signs.
- **Professor.** (B1) Dependent rows in the sign test: as above, with Diebold–Mariano and Harvey et al. cited. (B2) Minimums on distinct quarters, `n_rows` beside `n_quarters`. Ideas taken: leave-one-out `others_share`; `all_inside`; `not_shown` wording; relative-MAE skill; one headline cell. To the backlog (#188): a seasonal random walk with drift as a second benchmark (Foster 1977), and a Wilson interval beside the cluster bootstrap for few clusters.
- **Product-lead.** (1) `miss` meant the opposite of v0.9.7's: renamed to `miss` and `signed_miss`. (2) Units: `miss_unit` on every row and summary, money stated. (3) The headline cell named; `share_by_origin` explains Q5 and Q6 differing. (4) `width`, `target_in_interval`, `n_quarters`, `n_clusters`, `basis_changes_outside` added. Ideas taken: `no_benchmark`; `below` spelt out; timing; the Q6 "Hoy" wording.
- **Explainer.** Units; one counting basis; how a basis flag is read; d and the all-ties case; the cache claim (dropped); failure paths (`no_benchmark`; a zero scale cannot occur); `now` for the default date: all written above.

## Results on real data (Step 3, nov.04.2026)

On the restored snapshot (schema 20, saved nov.04 05:51Z), as of 2026-11-02:

- **One forecast per group:** 920 of 920 revenue and 920 of 920 EBIT (company, quarter, horizon) groups hold one forecast.
- **Same ranges as M9:** every range the call shows, 2,770 of 2,770 (both pools and items, all eight companies), equals the stored `ranges_2026-11-02_1` row of the same origin to the cent, actual included.
- **Same benchmark as M3:** KO_2021-11-01, the one case on an origin's date: 8 of 8 benchmark forecasts equal the stored `naive_srw` rows.
- **Timing:** 8.0–12.4 seconds a company.

| Company | Quarters | Revenue: Warren's median miss vs the benchmark's | Warren closer (per quarter) | Verdict | EBIT median miss vs benchmark | EBIT verdict | Pooled range held (revenue) | Own range held (revenue) | Basis-change rows |
|---|---|---|---|---|---|---|---|---|---|
| AAPL | 30 | 9.3% vs 5.8% | 14 of 30 | not shown | 3.5 vs 2.7 pts | not shown | 79%, held | 71%, held | 0 |
| MSFT | 31 | 3.9% vs 13.8% | 29 of 31 | Warren better | 4.6 vs 7.9 pts | Warren better | 100%, too wide | 78%, held | 0 |
| WMT | 30 | 1.1% vs 5.2% | 27 of 30 | Warren better | 0.4 vs 0.3 pts | not shown | 100%, too wide | 80%, held | 0 |
| KO | 31 | 5.5% vs 6.7% | 15 of 31 | not shown | 6.1 vs 4.0 pts | not shown | 88%, held | 78%, held | 13 |
| PG | 31 | 2.9% vs 3.4% | 20 of 31 | not shown | 1.3 vs 1.3 pts | not shown | 100%, too wide | 57%, too narrow | 3 |
| JNJ | 31 | 3.3% vs 5.5% | 18 of 31 | not shown | 4.4 vs 8.4 pts | Warren better | 89%, held | 71%, held | 15 |
| CAT | 30 | 15.3% vs 12.5% | 12 of 30 | not shown | 3.3 vs 3.8 pts | not shown | 71%, held | 85%, held | 0 |
| XOM | 28 | 29.9% vs 13.1% | 3 of 28 | benchmark better | 7.9 vs 7.4 pts | not shown | 26%, too narrow | 82%, held | 15 |

What it shows: Warren clearly beats last year's quarter on the steady growers (MSFT and WMT revenue, MSFT and JNJ EBIT) and clearly loses on Exxon's revenue, where carrying forward a trend through the 2020 crash and the 2022 spike missed by about 30% at the median; everywhere else the record cannot tell Warren from the benchmark with about 30 quarters. The pooled range is too wide for MSFT, WMT and PG (every quarter inside) and far too narrow for XOM, as v0.9.8 found; the company's own range fits better except at PG.
