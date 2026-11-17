# Backlog #189: the M10 grid dates in a company's track record

Issue: https://github.com/sonderbot-ar/warren/issues/189 · Branch `backlog-189-grid-track-record` · Version v0.10.1 when merged.

## Problem

Brief question 6 ("¿Qué tan bien ha pronosticado Warren a Procter & Gamble en el pasado?") is answered by `track_record` (v0.9.14, #145) from M9's monthly origins only. Its design left the case batches out: M3's and M8's dates were chosen around events, so they are not a fair sample of a company, and M10 was not merged (`docs/designs/backlog-145-track-record.md`, Alternatives). M10 merged on nov.17.2026 (v0.10.0): 168 grid cases on 22 dates chosen by a calendar rule fixed before any result, scored in batch `eval_2026-11-17_1` with `actual_filed_at` filled on every scored row, so they can be cut point in time. The brief's Q6 "Hoy" line still says "the case batches join when M10 merges".

The grid adds two things the monthly history does not have:

1. **Other dates.** Mid-quarter 15ths, a week or two after most 10-Qs, and the 1st and 15th of each month after the models' cutoff. Many of their baseline forecasts are the same as a monthly origin's (same filings known), so the section says how many (`grid_repeats_monthly`) and is never pooled with the monthly rows.
2. **The news step.** Each grid case also has the forecast with the AI's news shocks (`llm_masked`, M10's headline variant). The monthly record is the baseline alone (`baseline_only`). For a student, "how did Warren do on P&G" includes "did reading the news help on P&G". The answer per company is shown, but never tested: M10 tested the news step once, pooled over all companies by date, and found a gain **not shown**; eight companies × two items of per-company tests would give about one false "helped" by chance (professor's multiple-testing point in #145). So per company the section gives the numbers and no verdict, and points to M10's pooled answer.

The event case library (M3, M8) stays out, as before.

## What changes

`track_record(...)` gains a field `grid` (a `GridSection`, or None when no grid batch is stored). Everything else in the call is unchanged: the monthly rows, summaries, headline and notes keep their fields and values; the only text that changes is the `cases_not_included` note's (now "the event case library is not included…; the grid dates are, in their own section").

As of D, for the company:

1. **Which batches.** Every stored batch whose cases are all `event_type = 'grid'` (`eval_batches` joined to `eval_cases`; today `eval_2026-11-17_1`). A later batch re-scores the same cases with newer actuals (Walmart's December 10-Q); for one case and quarter the row of the newest batch (by `created_at`, then `batch_id`) that has it `ok` with `actual_filed_at` set is used. A row without `actual_filed_at` (a batch stored before migration 0018) can't be cut point in time and is never used. `batch_ids` lists the batches read.
2. **Rows.** For each (target quarter, horizon) of the company whose case date is before D and whose baseline revenue and EBIT actuals were both filed on or before D: one row from the **earliest** grid case that forecast it (as the monthly rows; `n_cases` counts the cases dated before D that forecast it, and `cases_differ` is true if their baseline forecasts are not all equal to 1e-9 relative). The row has the monthly row's fields with `case_id` in place of `origin_id` (and `n_cases` for `n_origins`), plus `post_cutoff` (`grid.is_post_cutoff` on the case date). Per item:
   - forecast, actual, miss and signed miss: the batch's `baseline` row (`harness.score` on its forecast, actual and `actual_revenue`, so the miss is the batch's own `error`);
   - the benchmark: M3's seasonal random walk read from the case run's own history rows (`track_record.benchmark`), which is how the batch built its `naive_srw` row (checked equal on real data, Step 3); and the drift benchmark (#188) the same way as the monthly rows, with the basis check;
   - the range per pool: M9's p10–p90 rebuilt for the case on its own date from the misses known that day (`ranges.subject_rows` with the case as a subject, seeded by its case id, as `ranges test --batch` built it; checked equal to the stored build `ranges_2026-11-17_1`, Step 3). `no_history` when the pool was short of misses that day (the 2019 and 2020 grid dates). No `warm_up`: M9's rolling test start applies to monthly origins, while every grid case's range was built and scored by M10;
   - **`news`**: the `llm_masked` row of the same batch: `forecast` (the shocked median), `miss`, `signed_miss`, `moved` (its forecast differs from the baseline's by more than 1e-9 relative; a case without shocks takes the baseline forecast, M8's intention-to-treat reading, so `moved` false), and `closer` (`news`, `baseline`, `tie`). `missing` `no_news_row` when the batch has no masked row for the quarter.
   - `basis_change`: v0.9.7's detector run on the case's run with filings public by D (`hindsight.against_actuals`, as `run_ranges.basis_flags` does for origins).
3. **Summaries**, per item and horizon (1–4 and all), built by the same code as the monthly ones (`summaries`), so the same rules hold: misses and skill against both benchmarks, the sign test per target quarter over all horizons and on rows at h1, no verdict at h ≥ 2, `few_quarters` under 12 distinct quarters; the range cells with the grid's own leave-one-out `others_share` (the other companies' grid rows) and `share_by_origin` counted per case. Plus `news` per cell: `n_rows`, `n_moved`, Warren's mean miss without and with news on the same rows, `skill` (1 − with ÷ without), wins, losses and ties on the moved rows, and the sign test's p on them, with **no verdict** and the note `news_not_tested_per_company` (params `pooled_answer` `not_shown`, `version` `v0.10.0`).
4. **Section notes.** `grid_rule` (the dates were set by a calendar rule before any result, M10), `grid_repeats_monthly` (params `n_rows`, `n_same`: rows whose baseline forecast equals the monthly row's for the same quarter and horizon to 1e-9 relative), `news_not_tested_per_company`, `not_yet_scorable` (params `case_ids`: the company's grid cases dated before D with no row yet, such as Walmart's latest), and `left_out` (params `dates`: grid dates the company is not on, Exxon's eight since 2026-02-15, from `grid.grid_cases`). `missing` `no_grid_record` when the company has no grid row by D.

The section has no headline: the screen leads with the monthly `headline` cell as today, and shows the grid section below it. Point in time as the monthly part: cases dated before D, actuals filed by D, ranges from misses known on the case date, basis flags from filings public by D. Nothing is written; no migration.

## Steps

- **Step 0.** This design doc and its review.
- **Step 1.** `domains/evaluation/track_record.py`: `grid_batches`, `grid_rows`, `news_summary`, `GridSection`, wired into `track_record` (and `summaries` generalised to take the section's own range rows). Tests in `tests/evaluation/test_track_record.py` on a migrated database with synthetic grid cases and batches: a case dated D is not used and D − 1 is; an actual filed D + 1 is not used, nor one with no `actual_filed_at`; revenue filed by D and EBIT after D is not used; two cases forecasting one quarter and horizon give one row from the earliest, `n_cases` 2; a newer batch's row wins for the same case and quarter; a batch holding a non-grid case is not read; the miss equals the batch's stored `error`; the benchmark equals the run's history row a year earlier; `news.moved` false when the masked forecast equals the baseline, `closer` on a tie; `news` summary counts and no verdict; `grid_repeats_monthly` counts a repeated forecast; `not_yet_scorable` lists a case with no ok row; the monthly part of `to_dict` is unchanged by the grid (same dict with and without a grid batch, but for `grid` and the `cases_not_included` text); no grid batch gives `grid` None; `to_dict` round-trips through `json`. Exit: green.
- **Step 2.** The command `track-record` prints the grid section after the monthly one (summary table with the news columns, then the quarters), `--json` as before. Tests in `tests/evaluation/test_cli.py`. Exit: green; ruff clean.
- **Step 3.** Real data on the restored snapshot, as of 2026-11-16 (the batch's `actuals_as_of`): every grid row's baseline and masked misses equal the batch's stored `error`; every benchmark equals the batch's `naive_srw` row; every range equals the stored `ranges_2026-11-17_1` baseline row for the same case to the cent; the monthly part is identical to `main`'s for all eight companies; the eight companies' grid summaries written below with the timing. Exit: equalities hold.

**Exit criterion:** all tests pass; Step 3's equalities hold; `docs/team-sync.md` names the section and its fields; brief Q6's "Hoy" line updated.

## Alternatives considered

- **Pool the grid rows with the monthly rows.** Rejected: many grid forecasts repeat a monthly one, so pooling would count one forecast twice (the #145 analyst's finding), and the two samples were drawn by different rules.
- **Test the news step per company.** Rejected (see Problem): 16 tests on about 20 cases each, against one pre-registered pooled test that found no gain. The numbers are shown; the verdict stays M10's.
- **Read the stored ranges of the build instead of rebuilding them.** Rejected: a build is tied to one `actuals_as_of` and might not exist for a later batch; the rebuild is the same code with the same seed (checked equal in Step 3) and keeps the call independent of which builds were run, as the monthly part is.
- **Show `llm_named` too.** Left out: M10's headline is masked, and named can lean on the model's memory before the cutoff. Named is one field away if the front-end team asks.
- **Add the M3 and M8 event cases.** Still out: chosen around events, and M8's batch has no `actual_filed_at`.

## Files to change

Changed: `domains/evaluation/track_record.py`, `domains/evaluation/__main__.py` (only if the renderer needs it), `tests/evaluation/test_track_record.py`, `tests/evaluation/test_cli.py`; at merge `docs/versions.md`, `docs/team-sync.md`, `docs/product/brief.md` (Q6 "Hoy"), this doc's results.

## Product impact

Serves brief question 6 and design principle 4 (show the uncertainty measured). Q6's "Hoy" drops "the case batches join when M10 merges" and names the grid section. Added: the top-level field `grid`. Changed: the English text of `cases_not_included`. Nothing renamed or removed; no existing value changes.

Fields of `grid` (`to_dict`):

- `batch_ids`, `rows[]`, `summaries[]`, `notes[]`, `missing`;
- a row: `period`, `period_end`, `horizon`, `made_on` (the case date), `case_id`, `run_id`, `n_cases`, `cases_differ`, `post_cutoff`, `basis_change`, `items` {`revenue`, `ebit`}, each with the monthly item fields (`forecast`, `actual`, `filed_at`, `miss`, `signed_miss`, `miss_unit`, `benchmark_*`, `closer`, `ranges`, `drift`) plus `news` {`variant` (`llm_masked`), `forecast`, `miss`, `signed_miss`, `moved`, `closer` (`news`, `baseline`, `tie`), `missing`};
- a summary: the monthly summary's fields plus `news` {`n_rows`, `n_moved`, `mean_miss_without`, `mean_miss_with`, `skill`, `wins`, `losses`, `ties`, `sign_p`, `notes[]`};
- codes the app needs words for: `no_grid_record`, `no_news_row`; notes `grid_rule`, `grid_repeats_monthly`, `news_not_tested_per_company`, `not_yet_scorable`, `left_out`; `closer` values `news`, `baseline`.

Suggested reading for the screen: a heading such as "Fechas fijadas de antemano" over the section, with `grid_rule` under it; the news line as "Con noticias: el error medio pasó de X a Y en los N trimestres que las noticias movieron", never "ayudó" or "empeoró" as a verdict, and `news_not_tested_per_company` beside it.
