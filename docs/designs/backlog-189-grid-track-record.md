# Backlog #189: the M10 grid dates in a company's track record

Issue: https://github.com/sonderbot-ar/warren/issues/189 · Branch `backlog-189-grid-track-record` · Version v0.10.1 when merged.

## Problem

Brief question 6 ("¿Qué tan bien ha pronosticado Warren a Procter & Gamble en el pasado?") is answered by `track_record` (v0.9.14, #145) from M9's monthly origins only. Its design left the case batches out: M3's and M8's dates were chosen around events, so they are not a fair sample of a company, and M10 was not merged (`docs/designs/backlog-145-track-record.md`, Alternatives). M10 merged on nov.17.2026 (v0.10.0): 168 grid cases on 22 dates chosen by a calendar rule fixed before any result, scored in batch `eval_2026-11-17_1` with `actual_filed_at` filled on every scored row, so they can be cut point in time. The brief's Q6 "Hoy" line still says "the case batches join when M10 merges".

The design review (below) found, on the real data, that the grid's baseline forecasts are almost all ones the monthly history already holds: 850 of 866 (quarter, horizon, item) forecasts equal the earliest monthly origin's to the cent, because on a grid date Warren knew the same filings as on the 1st of the month before. A grid copy of the baseline's record (misses, benchmarks, ranges, verdicts) would show the monthly answer again on a sub-sample, and a student would read it as new evidence. What the grid does add is **the news step**: on each grid date Warren also forecast with the AI's news shocks (`llm_masked`, M10's headline variant), and each date read its own week of news. The monthly record is the baseline alone (`baseline_only`). For a student, "how did Warren do on P&G" includes "did reading the news help on P&G".

So the grid section is the news step per company, shown and not tested. M10 tested the news step once, pooled over all companies by date, and found a gain **not shown**; eight companies × two items of per-company tests would give about one false "helped" by chance (Benjamini & Hochberg 1995; the professor's multiple-testing point in #145). Per company the section gives the numbers, no verdict and no p-value, and points to M10's pooled answer. The event case library (M3, M8) stays out, as before.

## What changes

`track_record(...)` gains a field `grid` (a `GridSection`, or None when no grid batch is stored). Everything else in the call is unchanged: the monthly rows, summaries, headline and notes keep their fields and values; the only text that changes is the English of the `cases_not_included` note, now "the event case library is not included: its dates were chosen around events, so they are not a fair sample of the company; the grid dates are, in their own section".

As of D, for the company:

1. **Which batch.** The newest stored batch (by `created_at`) whose cases are all `event_type = 'grid'` and whose `code_version` does not end in `+dirty` (today `eval_2026-11-17_1`; `eval_2026-11-03_1` came before M10's no-shock scoring fix and `eval_2026-11-03_2` is dirty). Every grid batch re-scores every grid case on the same stored run, so the newest holds the latest actuals; baseline and news rows always come from that one batch, never mixed. A batch created after D is fine: its forecasts are each case's own, made on the case date, and its actuals are cut at D below. `batch_id` names it.
2. **Rows, case by case.** For each grid case of the company dated before D, each forecast quarter whose baseline revenue and EBIT rows are both `ok` with `actual_filed_at` on or before D (a row without `actual_filed_at` is never used). No deduplication across cases: each date read different news, so each case's news forecast is its own evidence (analyst). A row: `case_id`, `made_on` (the case date), `post_cutoff` (`grid.is_post_cutoff`: the case's news week starts after the models' training cutoff), `run_id`, `period`, `period_end`, `horizon`, `same_as_monthly` (both baseline forecasts within half a cent of the monthly row's for that quarter and horizon; None when the monthly section has no such row), and per item:
   - `forecast`, `actual` (first reported), `filed_at`, `miss`, `signed_miss` (positive: too high), `miss_unit`: the batch's baseline row, scored by `harness.score` as the batch scored it;
   - `news_forecast`, `news_miss`, `news_signed_miss`: the batch's `llm_masked` row. A case with no masked row had no shocks, and the baseline stands in (`news_from_baseline` true), as M8's `backtest.pairs` fills it (intention to treat: 125 of 167 scored cases);
   - `moved`: the news forecast differs from the baseline's by more than half a cent (M8's `backtest.CENT`), on this quarter;
   - `closer`: `news`, `baseline` or `tie` (absolute misses within 1e-12).
3. **Summaries**, per item and horizon (1–4, and None for all together): `news`, three parts, `all`, `pre_cutoff` and `post_cutoff` (before the cutoff the model may remember what happened next, M10's memory test; product lead and professor). Each part: `n_rows` (forecasts, a case and a quarter), `n_cases`, `n_quarters` (distinct target quarters), `n_moved`; the mean miss without and with news over all `n_rows` (a quiet date counts as a tie, M10's headline reading) and `skill` (1 − with ÷ without); the same two means over the moved rows only; and wins, losses and ties among the moved rows. `few_moved` (params `n_moved`, `min_moved` 6, the minimum past events uses) when fewer than 6 moved. **No p-value and no verdict** (professor B1 and S1): a p beside "not tested" invites the reading the design rules out.
4. **Section notes.** `grid_rule` (the dates were set by a calendar rule before any result, M10), `news_not_tested_per_company` (params `pooled_answer` `not_shown`, `version` `v0.10.0`, constants), `news_means` (which rows each mean covers), `grid_repeats_monthly` (params `n_rows`, `n_same`: rows whose baseline equals the monthly forecast), `not_yet_scorable` (params `case_ids`: the company's grid cases dated before D that the batch holds but with no quarter scorable by D, such as Walmart's four latest, whose rows are all `missing` until its December 10-Q), `grid_cases_failed` (params `case_ids`, `batch_id`: the company's grid cases dated before D with no forecast in the batch, today XOM_2023-11-15, whose run failed), and `left_out` (params `dates`: grid dates before D in `eval_cases` the company is not on, Exxon's eight from 2026-02-15). `missing` `no_grid_record` when the company has no grid row by D (the section is still returned, with its notes).

Point in time: cases dated before D, actuals filed by D, the case runs' forecasts as made on their dates. Nothing is written; no migration.

## Steps

- **Step 0.** This design doc and its review.
- **Step 1.** `domains/evaluation/track_record.py`: `grid_batch`, `grid_rows`, `news_summary`, `grid_summaries`, `grid_section`, wired into `track_record`. Tests in `tests/evaluation/test_track_record_grid.py` on a migrated database with synthetic grid cases and a batch: a case dated D is not used and D − 1 is; an actual filed D + 1 is not used, nor one with no `actual_filed_at`; revenue filed by D and EBIT after D is not used; two cases forecasting one quarter give two rows; the newest clean batch is read and a `+dirty` one or a batch holding a non-grid case is not; the miss equals `harness.score` on the batch row; a case with no masked row takes the baseline (`news_from_baseline`, not moved, tie); a masked forecast half a cent away is not moved and one cent away is; wins and losses count moved rows only; means over all rows and over moved rows; the cutoff split; `few_moved` at 5 and not 6; no `sign_p` or `verdict` field; `same_as_monthly`; `not_yet_scorable`, `grid_cases_failed` and `left_out`; `no_grid_record`; the monthly part of `to_dict` is the same with and without a grid batch (but for `grid` and the `cases_not_included` text); no grid batch gives `grid` None; `to_dict` round-trips through `json`. Exit: green.
- **Step 2.** The command `track-record` prints the grid section after the monthly one (the news table per item, then the notes), `--json` as before. Tests in `tests/evaluation/test_cli.py`. Exit: green; ruff clean.
- **Step 3.** Real data on the restored snapshot, as of 2026-11-16 (the batch's `actuals_as_of`): every grid row's baseline and news misses equal the batch's stored `error`; over all eight companies the rows are exactly the batch's ok baseline quarters (1,030 rows ÷ 2 items); the monthly part is identical to `main`'s for all eight companies; the eight companies' news numbers written below with the timing. Exit: equalities hold.

**Exit criterion:** all tests pass; Step 3's equalities hold; `docs/team-sync.md` names the section and its fields; brief Q6's "Hoy" line updated.

## Alternatives considered

- **Pool the grid rows with the monthly rows.** Rejected: many grid forecasts repeat a monthly one, so pooling would count one forecast twice (the #145 analyst's finding), and the two samples were drawn by different rules.
- **Test the news step per company.** Rejected (see Problem): 16 tests on about 20 cases each, against one pre-registered pooled test that found no gain. The numbers are shown; the verdict stays M10's.
- **A full grid copy of the baseline's record (benchmarks, ranges, verdicts), one row per quarter and horizon from the earliest case.** The first draft. Rejected at review: 850 of 866 such forecasts repeat a monthly one (analyst), so it would restate the monthly answer on a sub-sample and could disagree with it on noise (professor S2, product lead); and keeping the earliest case alone threw away the news of later dates (P&G's only two moved forecasts, 4 of Exxon's 7; analyst B1).
- **A sign test on the moved rows.** Rejected: its unit (rows sharing an actual, overlapping horizons) would need #145's per-quarter rule, and any p beside "not tested" invites a verdict (professor B1, S1).
- **Show `llm_named` too.** Left out: M10's headline is masked, and named can lean on the model's memory before the cutoff. Named is one field away if the front-end team asks.
- **Add the M3 and M8 event cases.** Still out: chosen around events, and M8's batch has no `actual_filed_at`.

## Files to change

Changed: `domains/evaluation/track_record.py` (and its `render`), `tests/evaluation/test_track_record_grid.py` (new), `tests/evaluation/test_cli.py`; at merge `docs/versions.md`, `docs/team-sync.md`, `docs/product/brief.md` (Q6 "Hoy"), this doc's results.

## Product impact

Serves brief question 6 and design principle 4 (show the uncertainty measured). Q6's "Hoy" drops "the case batches join when M10 merges" and names the grid section. Added: the top-level field `grid`. Changed: the English text of `cases_not_included` (its code and params stay). Nothing renamed or removed; no existing value changes.

Fields of `grid` (`to_dict`):

- `batch_id`, `rows[]`, `summaries[]`, `notes[]`, `missing`;
- a row: `case_id`, `made_on`, `post_cutoff`, `run_id`, `period`, `period_end`, `horizon`, `same_as_monthly`, `items` {`revenue`, `ebit`}, each with `forecast`, `actual`, `filed_at`, `miss`, `signed_miss`, `miss_unit`, `news_forecast`, `news_miss`, `news_signed_miss`, `news_from_baseline`, `moved`, `closer` (`news`, `baseline`, `tie`);
- a summary: `item`, `horizon` (1–4 or null), `miss_unit`, `news` {`all`, `pre_cutoff`, `post_cutoff`}, each with `n_rows`, `n_cases`, `n_quarters`, `n_moved`, `mean_miss_without`, `mean_miss_with`, `skill`, `mean_miss_without_moved`, `mean_miss_with_moved`, `wins`, `losses`, `ties`, `missing`;
- misses are fractions in `miss_unit`, money in whole currency units, as the monthly part;
- codes the app needs words for: `no_grid_record`, `few_moved`; notes `grid_rule`, `news_not_tested_per_company`, `news_means`, `grid_repeats_monthly`, `not_yet_scorable`, `grid_cases_failed`, `left_out`; `closer` values `news`, `baseline`, `tie`; `post_cutoff`'s meaning (the AI's news week starts after the models' training cutoff, so the model cannot remember the outcome).

Suggested Spanish (product lead), for the front-end team to settle: heading "Fechas fijadas de antemano", then `grid_rule` as "Warren fijó estas fechas con una regla de calendario antes de ver ningún resultado, para no quedarse solo con las fechas en que le fue bien."; `grid_repeats_monthly` "{n_same} de estos {n_rows} pronósticos base son iguales a los del historial mensual: no son evidencia nueva."; the news line "Con noticias (los supuestos que propone la IA al leer las noticias de la semana; Warren calcula el número): en los {n_moved} pronósticos que las noticias movieron, el error medio pasó de {X} a {Y}." Use "pronósticos", not "trimestres" (a row is a case and a quarter); never "ayudó" or "empeoró" as a verdict; `news_not_tested_per_company` "Con tan pocos casos por empresa no se puede saber si las noticias ayudaron. Warren lo probó con todas las empresas juntas (v0.10.0) y no encontró una mejora demostrada." ("no demostrada", never "no ayuda"). Lead with the `post_cutoff` part where it is not `few_moved`. Adding the news line to the Q6 screen is part of the Q6 mockup the owner signs off (front-end rule), not of this change.

## Design review (nov.17.2026)

Explainer, analyst, professor and the front-end product lead, in parallel, on the first draft. Analyst NO-GO (3 blockers), professor NO-GO (1), product lead 2 blockers, explainer 12 gaps; the design was rebuilt around them (the text above is the revised design).

- **Analyst.** (B1) One row per quarter and horizon from the earliest case lost later dates' news (P&G 2 → 0 moved, Exxon 7 → 3, Coca-Cola 13 → 9, JNJ EBIT 18 → 13, Apple EBIT 19 → 15): rows are now per case. (B2) Only 42 of 167 scored cases store a masked row; the rest had no shocks: the baseline now stands in, as M8 (`backtest.py:62-85`), and `no_news_row` is gone. (B3) `not_yet_scorable` would have named XOM_2023-11-15 (failed) and missed Walmart's four (rows, all `missing`): now two codes, as above. Ideas taken: 850 of 866 baseline forecasts repeat the monthly ones (the reason for the redesign); one clean batch, never mixed; `few_moved`; M8's half cent for "moved". Checked and holding: every ok row of the batch has `actual_filed_at` (0 nulls); `naive_srw` equals the run's history a year earlier on 1,328 of 1,328 rows; grid actuals equal the monthly ones on 994 of 994.
- **Professor.** (B1) The news p's unit was unspecified and a row-level p overstates: the p is dropped (S1). (S2) Grid verdicts against the benchmarks would undo #145's "two verdicts per company and item": the grid no longer repeats the baseline's record. (S3) Split by `post_cutoff`: done. (S4) Say which rows each mean covers: `news_means`, and moved-only means added. Ideas for the app: a lesson "why we don't say news helped P&G" (16 tests, about one false hit), and a view pairing monthly and grid rows.
- **Product lead.** (1) Pre- and post-cutoff mixed in the news line: split. (2) The suggested Spanish said "trimestres" for rows and its means' rows were unclear: "pronósticos", and both means given. Ideas taken: Spanish for every note, `tie` in the codes list, say that the AI proposes and Warren computes. The Q6 screen's news line goes to the owner with the Q6 mockup.
- **Explainer.** Batch choice before D (any batch, actuals cut at D), "earliest" and the per-row fields (moot now: rows per case), the dates (the M10 doc lists all 22), which run (the batch's own, per case), the tie tolerance, the empty-company case (`no_grid_record` on a returned section), `left_out` cut at D, the full `cases_not_included` text, and `pooled_answer` a constant: all written above. The drift benchmark and ranges questions are moot (the grid no longer carries them).

## Results on real data (Step 3, nov.17.2026)

On the restored snapshot (`warren-20261117T051108Z`, schema 23), as of 2026-11-16, batch `eval_2026-11-17_1`:

- **Rows are the batch's:** 515 grid rows over the eight companies, exactly the batch's 515 scored baseline quarters (1,030 ok rows ÷ 2 items); every baseline and news miss equals the batch's stored `error` (0 mismatches); every case without a masked row takes the baseline.
- **Same as M10, pooled:** over all 515 rows, 1 − mean miss with news ÷ without is +0.43% (revenue) and +0.63% (EBIT), M10's headline masked skill (+0.4%, +0.6%).
- **The monthly part is unchanged:** for all eight companies `to_dict` without `grid` equals `main`'s, but for the `cases_not_included` text.
- **The baseline repeats the monthly history:** 497 of 515 rows have both baseline forecasts equal to the monthly forecast of the same quarter and horizon.
- **Timing:** 4.1–5.2 seconds a company with the grid section, about the same as before.

All horizons together, the news forecast against the baseline (mean misses over every grid forecast; "moved" counts the forecasts the news changed; "few" is under 6 moved):

| Company | Grid forecasts | Revenue: moved | Revenue mean miss, without → with | News closer / baseline closer | EBIT: moved | EBIT mean miss, without → with (pts) | News closer / baseline closer | Notes |
|---|---|---|---|---|---|---|---|---|
| AAPL | 67 | 8 | 9.63% → 9.48% | 5 / 3 | 19 | 3.71 → 3.67 | 10 / 9 | |
| MSFT | 67 | 6 | 3.94% → 4.17% | 1 / 5 | 9 | 4.76 → 4.69 | 6 / 3 | |
| WMT | 62 | 7 | 1.60% → 1.65% | 2 / 5 | 12 | 0.41 → 0.40 | 8 / 4 | 4 dates wait for its December 10-Q |
| KO | 68 | 13 | 9.62% → 9.03% | 11 / 2 | 13 | 6.60 → 6.56 | 8 / 5 | |
| PG | 68 | 2 (few) | 3.17% → 3.23% | 0 / 2 | 2 (few) | 3.69 → 3.68 | 1 / 1 | |
| JNJ | 67 | 6 | 7.01% → 7.28% | 0 / 6 | 18 | 8.05 → 8.01 | 8 / 10 | |
| CAT | 68 | 1 (few) | 16.30% → 16.17% | 1 / 0 | 1 (few) | 4.22 → 4.19 | 1 / 0 | |
| XOM | 48 | 7 | 35.95% → 35.89% | 6 / 1 | 7 | 11.87 → 11.85 | 5 / 2 | 1 failed date, 8 left out; no date after the cutoff |

What it shows: on most companies the news moved few forecasts and moved them a little, so the mean miss barely changes. Coca-Cola's revenue is the one place where the news looks clearly useful (11 of 13 moved forecasts closer, mostly before the models' cutoff, when the model may remember what happened); on Microsoft's and JNJ's revenue the news made things worse on most moved forecasts. None of this is tested per company, by design; the pooled answer stays M10's "not shown".
