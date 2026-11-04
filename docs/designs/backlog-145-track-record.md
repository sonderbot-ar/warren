# Backlog #145: a company's track record

Issue: https://github.com/sonderbot-ar/warren/issues/145 · Branch `backlog-145-track-record` · Version v0.9.14 when merged.

## Problem

The front-end team's request R4 (brief question 6, `docs/product/brief.md` §5: "¿Qué tan bien ha pronosticado Warren a Procter & Gamble en el pasado?"). The brief asks, for one company: past forecasts beside the first-reported actuals, quarter by quarter, the error, how often the range held the actual, and the same for a simple benchmark (last year's quarter carried forward), with the company's own miscalibration shown, not pooled away. Today every stored history pools companies: M3 and M8 report all cases together (`domains/evaluation/report.py`, `backtest_report.py`), M9 reports coverage pooled with a per-company table (`ranges_report.py`), and v0.9.8's `run_ranges` gives a company's coverage but not its forecasts, misses or the benchmark.

## What the history is

The track record is M9's monthly origins (`forecast_origins`, `baseline_errors`, migration 0017): the baseline run as of the 1st of every month since 2019-04 for every company, each forecast quarter 1–4 scored against the actual as first reported, with the date that actual was filed. That is the systematic history (about 30 target quarters and 115 quarter-and-horizon pairs per company). The case batches of M3 and M8 are not used here; see Alternatives.

**One row per target quarter and horizon, not per origin.** Monthly origins repeat a forecast until a new filing lands, so one target quarter is scored at the same horizon by up to three origins. On the restored data every such group holds one forecast: 920 of 920 revenue groups and 920 of 920 EBIT groups have a single distinct forecast (query in Step 3). So a row is (target quarter, horizon), taken from the **earliest** origin in its group: the first date Warren made that forecast. `n_origins` says how many monthly origins repeated it. This is what a student reads as "Warren's forecast for P&G's Q3, made two quarters ahead", and it stops the summaries from counting one miss three times (the #144 analyst's finding).

## What changes

A new call `domains.evaluation.track_record.track_record(conn, ticker, as_of=None, n=10_000) -> TrackRecord`, and a command `python -m domains.evaluation track-record --ticker T [--as-of D] [--json]`. Without a date it uses `shared_kernel.calendar.last_ended_day` (as v0.9.7's commands do) and says so. As of D:

1. **Rows.** For each (target quarter, horizon 1–4) of the company whose earliest origin is dated before D and whose revenue and EBIT actuals were both filed on or before D (`actual_filed_at`, the later of the two, as M9's `load_pairs`), with both errors `ok`:
   - `period`, `period_end`, `horizon`, `made_on` (the earliest origin's date), `origin_id`, `run_id`, `n_origins` (origins dated before D in the group);
   - per item (`revenue`, `ebit`): `forecast`, `actual` (first reported), `filed_at`, and `miss` as M3 scores it (`harness.score`: signed (forecast − actual) / |actual| for revenue, / |actual revenue| for EBIT, margin points), with `abs_miss`;
   - the **benchmark**, M3's seasonal random walk (`naive_srw`): the same quarter a year earlier as known on `made_on`, read from the origin run's own stored history rows (`history:revenue`, `history:ebit` at period − 4, `runs.load_assumptions`), exactly as `harness.evaluate_case` builds it; its `forecast`, `miss`, `abs_miss`; `closer`: `warren`, `benchmark` or `tie` (equal absolute misses to 1e-12);
   - the **range** per pool (`pooled`, `own`): M9's p10–p90 as built on `made_on` from the misses known that day, seeded by the origin id (`run_ranges.scored_origin_rows`'s rows, which are M9's rolling test: origins from 2021-01-01). Each gives `p10`, `p90` and `held`: `inside`, `below` or `above` (ends count as inside, as M8). Before 2021 the range is `warm_up` (M9's first 21 months build the history, they are not scored); a pool short of misses that day is `no_history`;
   - `basis_change`: the v0.9.7 detector (`run_ranges.basis_flags`, filings public by D) flags this row's quarter as a change of reporting basis (JNJ after Kenvue, KO 2019). The row stays in: until #162, M9 counts it as a miss, and the student sees why.
2. **Summaries** per item, per horizon 1–4 and over all horizons (`horizon` None):
   - `n_quarters` (rows), Warren's and the benchmark's median and mean absolute miss, `wins`, `losses`, `ties` (Warren closer, benchmark closer), the exact two-sided sign test on them (`backtest.sign_test`, M8's) and a coded `verdict`: `warren_better` or `benchmark_better` when p < 0.05, else `no_clear_difference`; `few_quarters` (params `n_quarters`, `min_quarters` 12) when there are fewer than 12 rows, and then no verdict;
   - the **range's record** per pool: `inside`, `below`, `above`, `share`, the 90% cluster bootstrap by calendar quarter (`ranges_report.cluster_bootstrap`, M9's interval), `target` 0.80, `acceptable` [0.65, 0.95] and `verdict` (`held`, `too_narrow`, `too_wide`; `run_ranges.verdict`), `few_scored` under 12 scored rows;
   - beside the company's range share, `all_companies_share`: the same deduplicated share over all eight companies cut at D, and `differs_from_all` when it lies outside the company's interval, so the screen can say "for P&G the range held less often than for the others";
   - `basis_changes`: rows flagged in the cell.
   The over-all-horizons cell pools a company's four horizons, as M9's headline pools them (note `horizons_pooled`); horizon 4 has about 25 rows a company, which is why each horizon is shown too.
3. **Notes.** `deduplicated` (params `rows`, `origins`: one row per target quarter and horizon, from the first origin), `benchmark_is_srw`, `baseline_only` (the range and misses are the baseline's, not the news shocks'), `code_differs` (as v0.9.8, when the origins were built with more than one code version), `cases_not_included` (the case batches are left out, see Alternatives).

Everything is point in time: rows need the earliest origin dated before D and both actuals filed by D; the benchmark is the origin run's own history as known on its date; the ranges are built from misses filed by the origin's date; the basis flags read filings public by D. Nothing is written. A ticker not in the universe raises; a company with no scored row returns empty rows and the coded gap `no_track_record`.

All money is raw, in the company's currency (`currency`, `montecarlo._currency`; Decision 11). Misses are fractions. Gaps and notes are coded (`reported.Coded`: `code`, `params`, `text` in English), never raised.

## Steps

- **Step 0.** This design doc and its review.
- **Step 1.** `domains/evaluation/track_record.py`: `track_record`, `TrackRecord.to_dict`, helpers `rows_for`, `benchmark`, `summaries`, `range_cells`. Tests (`tests/evaluation/test_track_record.py`, synthetic origins in a migrated database as `test_run_ranges.py` builds them, plus stored runs for the history rows): three origins repeating one forecast give one row with `n_origins` 3 and `made_on` the earliest; an origin dated D is not used and one dated D − 1 is; an actual filed D + 1 is not used; revenue filed by D but EBIT after D is not used; the miss equals `harness.score`; the benchmark equals the run's `history:` row for period − 4 and its miss `harness.score` on it; `closer` on a tie; wins + losses + ties = n; the sign-test verdict at p just below and above 0.05; `few_quarters` at 11 and not 12; `held` inside at p10 exactly; `warm_up` before 2021; the range's p10/p90 equal `run_ranges.scored_origin_rows`'s for the same origin; `all_companies_share` and `differs_from_all`; a flagged basis change counted; the same call twice gives the same dict; `to_dict` round-trips through `json`; an unknown ticker raises; a company with no rows gives `no_track_record`. Exit: green.
- **Step 2.** The command: per item, a table of quarters (period, horizon, made on, forecast, actual, miss, benchmark miss, range held), then the summaries and the notes; `--json` prints `to_dict` only. Tests in `tests/evaluation/test_cli.py`. Exit: green; ruff clean.
- **Step 3.** Real data on the restored snapshot: the one-forecast-per-group check (920 of 920); for every company as of 2026-11-02, the call's range rows equal M9's stored `ranges_2026-11-02_1` rows for the same origins; the benchmark equals M3/M8's stored `naive_srw` rows wherever a case run is also an origin run; the eight companies' summaries written below with the timing. Exit: equalities hold.

**Exit criterion:** all tests pass; Step 3's equalities hold; `docs/team-sync.md` names the call and its fields; brief Q6's "Hoy" line updated.

## Alternatives considered

- **Use the M3 and M8 case batches too.** Left out for now. The 26 cases (three or four per company) were chosen around events, so they are not a fair sample of how Warren does on a company; their rows do not store the actual's filing date (`eval_results` has no `actual_filed_at`), so a point-in-time cut would need the scoring recomputed; and wherever a case date falls on a month's first day it is already an origin. The M10 batches (rule-chosen dates, some after the models' cutoff) are the right addition once M10 merges; filed as a follow-up with the case section.
- **One row per origin, as M9 scores.** Rejected: it counts one forecast up to three times and makes a company's record look surer than it is.
- **The latest origin in each group instead of the earliest.** Same forecast, but a later origin's range knows more misses. The earliest is the first time Warren said it, which is the honest "what did we say then".
- **Store the track record.** Rejected: it changes whenever new actuals are scored; the call is deterministic for a date and the stored misses (`errors_sha256` is returned so a cache can key on it).

## Files to change

New: `domains/evaluation/track_record.py`, `tests/evaluation/test_track_record.py`. Changed: `domains/evaluation/__main__.py` (`track-record`), `tests/evaluation/test_cli.py`; at merge `docs/versions.md`, `docs/team-sync.md`, `docs/product/brief.md` (Q6 "Hoy"), this doc's results.

## Product impact

Serves brief question 6 and design principle 4 (show the uncertainty measured). Q6's "Hoy" changes from "En parte … Request R4 (#145)" to "Sí" for the monthly history. No existing output, name or field changes; no migration.

Fields of `to_dict`: top `ticker`, `as_of`, `as_of_default` (true when the date was chosen as the last ended day), `currency`, `errors_sha256`, `rows[]`, `summaries[]`, `notes[]`, `missing`; a row `period`, `period_end`, `horizon`, `made_on`, `origin_id`, `run_id`, `n_origins`, `basis_change`, `items` {`revenue`, `ebit`} each {`forecast`, `actual`, `filed_at`, `miss`, `abs_miss`, `benchmark_forecast`, `benchmark_miss`, `benchmark_abs_miss`, `closer`, `ranges` {`pooled`, `own`} each {`p10`, `p90`, `held`, `missing`}}; a summary `item`, `horizon` (1–4 or None), `n_quarters`, `median_abs_miss`, `mean_abs_miss`, `benchmark_median_abs_miss`, `benchmark_mean_abs_miss`, `wins`, `losses`, `ties`, `sign_p`, `verdict`, `basis_changes`, `ranges` {`pooled`, `own`} each {`inside`, `below`, `above`, `n`, `share`, `interval`, `target`, `acceptable`, `verdict`, `all_companies_share`, `differs_from_all`, `missing`}, `missing`, `notes[]`. Codes the app needs words for: `no_track_record`, `few_quarters`, `few_scored`, `warm_up`, `no_history`, `warren_better`, `benchmark_better`, `no_clear_difference`, `held`, `too_narrow`, `too_wide`, `inside`, `below`, `above`, `warren`, `benchmark`, `tie`, and the notes `deduplicated`, `benchmark_is_srw`, `baseline_only`, `horizons_pooled`, `code_differs`, `cases_not_included`. Misses are signed fractions: positive means Warren forecast too high.
