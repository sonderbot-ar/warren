# Backlog #146: past events, by rule

Issue: https://github.com/sonderbot-ar/warren/issues/146 · Branch `backlog-146-past-events` · Version v0.9.34 when merged.

## Problem

The front-end team's request R5 (brief questions 10–15, `docs/product/brief.md` §3 "Eventos" and §5). Every *evento* answer must show past cases chosen by a stated rule, never by hand and never by an AI: for each case the company, date and source, how close it is to the question, what Warren forecast just before, what was reported after, quarter by quarter, and that miss beside Warren's usual miss for the company on quarters without an event, so an ordinary error is not read as the event's effect. It always shows how many cases there are (n), says when that is too few, warns when an acquisition changed the company's scope, and lists metrics to watch for that kind of event, each with a source. The owner's direction in #130: the impact of an event is never an LLM's output.

Today the cases, their baseline runs and their scores are stored (M3, M8), but there is no query: the app would have to pick cases itself.

## What the data is

- **The case library**, `domains/evaluation/cases.csv` (M3): 26 rows, 18 events of seven types (`guidance` 5, `restructuring` 4, `m_and_a` 3, `litigation` 2, `regulation` 1, `supply_chain` 1, `macro` 1) and 8 rule-dated `control` rows. Each has a source URL, a description, a horizon of 4 quarters, and `scope_change` text where a deal closed inside the horizon (MSFT ×3, KO, XOM, JNJ; "(h1-h4)", "(h3-h4)", "(h4)").
- **Each case's baseline run**: the backtest batches store one `baseline` row set per case in `eval_results`, and on the restored data every case has exactly one baseline run id across all three batches (`<case_id>_1`; query in Step 3). The run is made from data public the day before the event (M3's look-ahead guard).
- **What was reported after**: `hindsight.against_actuals(conn, run_id, actuals_on)` (v0.9.7, #128) already gives each forecast quarter of a run beside its first-reported actual in the filings public by a date, scored as M3 scores it, with the filings behind it and coded gaps (`not_reported`, `restated_basis`, `other_ebit_definition`, `zero_base`). It is point-in-time on the actuals.
- **The usual miss**: M9's monthly origins (`forecast_origins`, `baseline_errors`): the same baseline model run on the 1st of every month since 2019-04, scored per target quarter and horizon. v0.9.14's track record deduplicates them to one row per (target quarter, horizon), from the first origin that made the forecast (`track_record._group_rows`), keeping only rows whose actuals were filed by the date asked.

## What changes

A new call `domains.evaluation.past_events.past_events(conn, ticker, event_type, as_of=None, now=None) -> PastEvents`, and a command `python -m domains.evaluation past-events --ticker T --event-type E [--as-of D] [--json]`. It writes nothing. Without a date it uses `shared_kernel.calendar.last_ended_day(now)` and says so (`as_of_default`), as v0.9.7's commands do. `ticker` is the company the question is about; `event_type` is one of the case library's event types other than `control` (the question reader names it; the call refuses anything else with a coded error).

1. **The rule.** From `cases.csv` (read with `cases.load_cases`, so its validation applies), the call takes every case with `event_type` equal to the one asked, of any company, whose `event_date` is before D (an event after D had not happened yet). These are `cases`, and only these count in n. Controls and any type not in the file (M10's `grid` rows live in their own file, `grid_cases.csv`, and are never read) are never included. The rule's text and the case file's SHA-256 are in the answer (`rule`, `cases_sha256`), so the same file and date always give the same list.
   - Also returned, as context and **not** counted in n: `same_company_other_type`, the asked company's own cases of other types before D (brief Q12: Apple's February 2020 case is "close" to a supply question though it is filed as `guidance`). Each says its type.
   - Order: same company first, then by event date, newest first.
2. **Closeness**, per case: `same_company` (its ticker is the one asked) and `same_mechanism` (its event type is the one asked: true for `cases`, false for `same_company_other_type`). The mechanism is the event type until #147 adds theme tags; then the rule becomes "type and tags" and `same_mechanism` compares tags. `direction` (same or opposite, brief Q14) is null with the note `direction_not_recorded`: the case file has no direction column yet (#147).
3. **Per case**: `case_id`, `ticker`, `event_date`, `event_type`, `description`, `source_url`, `scope_change` (the file's text or null), `run_id` (the baseline run), `run_as_of`, and per forecast quarter 1–4 (`horizon_quarters` of the case):
   - from `hindsight.against_actuals(conn, run_id, D)`: `period`, `period_end`, `horizon`, and per item (`revenue`, `ebit`) `forecast`, `actual`, `miss`, `signed_miss` (positive: Warren forecast too high), `miss_unit`, `filings`, `missing` (its codes, unchanged);
   - `forecast_margin` and `actual_margin`: EBIT ÷ revenue, through `financial_math.ratio`, null when either side is missing (the brief asks for operating margin; the EBIT miss is already in margin points of actual revenue);
   - `scope_change`: true on the quarters the file's "(hN)" or "(hN-hM)" names, else false. On those quarters the miss is shown but not compared with the usual one (`usual` is null with the code `scope_change`): most of that gap is the acquired company's revenue being added, which the backtest also leaves out (`backtest.py`, M8);
   - `usual` per item: Warren's usual miss for **the case's company** at **the same horizon**, on target quarters without an event, from the monthly origins known by D: `n_quarters`, `median_miss` and `p90_miss` of the absolute misses (same unit as the event's miss), and `rank`, the share of those usual misses smaller than this quarter's miss (0.95: larger than 95% of the usual misses). `beyond_usual` is true when the miss is above `p90_miss`. With fewer than 12 usual quarters (M9's and #145's minimum) `beyond_usual` is null with the code `few_usual_quarters`. A quarter with no actual yet, or a coded gap, has `usual` null.
   - **Which quarters are "without an event"**: the company's (period, horizon) rows of the monthly origins, less every target period that any of the company's event cases (any type, not controls) forecast at horizons 1–4 in its baseline run, less the quarters v0.9.7's basis detector flags (`run_ranges.basis_flags`, filings public by D), since a change of reporting basis is not a forecast miss. The percentiles use `statistics.quantiles(..., method="inclusive")`.
4. **n and thin evidence.** `n` is the number of `cases` with at least one quarter reported by D; `n_listed` all `cases` (an event close to D may have nothing reported yet). `thin_evidence` is true when `n` is below 6, with the code `thin_evidence` (`n`, `threshold`). Six is the smallest n at which even an exact two-sided sign test on the cases (M8's `backtest.sign_test`) can reach p < 0.05 (all 5 of 5 agreeing gives p = 0.0625; 6 of 6 gives 0.031), so below it no count of cases can tell an event's misses from chance. With n = 0 the answer has `missing` `no_cases` (`event_type`, `as_of`): brief Q13's "No hay casos parecidos".
5. **Metrics to watch**, a checked-in table `domains/evaluation/event_metrics.csv` with columns `event_type`, `metric_id`, `metric`, `where_to_find`, `source`, `source_url`: two or three rows per event type (not `control`), each sourced to a US GAAP topic or an SEC Regulation S-K item that requires the disclosure, so a student can find it in the 10-K or 10-Q. Loaded and validated (every non-control type has at least one row, every row has a source, no unknown type, unique `metric_id`) by `past_events.load_metrics`; the answer returns the asked type's rows and the file's SHA-256. The text is English; the front-end translates it.
6. **Notes** on every answer: `rule` (the selection rule in words), `baseline_only` (the forecasts are the baseline's, without news shocks), `usual_from_monthly_forecasts` (the usual miss comes from the monthly forecasts, at the same horizon, on quarters without an event, known by D), `past_outcomes_not_forecast` (these are what happened after past events, not a forecast of the next one), `direction_not_recorded`; plus `thin_evidence` when it applies.

## Steps

- **Step 0.** This design doc and its review.
- **Step 1.** `domains/evaluation/event_metrics.csv` and `load_metrics` with its checks. Tests: the real file loads, every non-control event type has a row, a row without a source, an unknown type, a duplicate id and a missing column are each refused. Exit: green.
- **Step 2.** `domains/evaluation/past_events.py`: `past_events`, `PastEvents.to_dict`, `usual_misses`, `event_periods`, `scope_horizons`. Tests (`tests/evaluation/test_past_events.py`, in a migrated database with synthetic origins as `test_track_record.py` builds them, and stored case runs): the rule takes same-type cases of every company and no control; an event dated D is left out and one dated D − 1 is kept; same company sorts first; `same_company_other_type` is listed and not counted; an actual filed after D is not shown; a case's own forecast periods are not in the usual set, nor another event case's, but a control's are; a basis-flagged quarter is not in the usual set; the rank and `beyond_usual` on a hand-computed set; fewer than 12 usual quarters gives `few_usual_quarters`; "(h3-h4)" flags quarters 3 and 4 only and their `usual` is null; n 5 is thin, n 6 is not; n 0 gives `no_cases`; an unknown event type and `control` are refused with the code `unknown_event_type`; an unknown ticker is refused. Exit: green; ruff clean.
- **Step 3.** The command `past-events`: per case a table of quarters (period, forecast and actual revenue and margin, miss, usual median, rank), the metrics, the notes; `--json` prints `to_dict` only. Tests in `tests/evaluation/test_cli.py`. Exit: green.
- **Step 4.** Real data on the restored snapshot: one baseline run per case (query); the call for each brief question that has a stored case (Q10 MSFT `m_and_a`, Q12 AAPL `supply_chain`, Q14 XOM `macro`, Q15 WMT `guidance`, Q13 JNJ with a type that has no JNJ case) written below with the timing; each event quarter's forecast and actual equal the stored `eval_results` baseline row of the M8 batch (`eval_2026-11-02_1`) where that row is `ok`. Exit: equalities hold.

**Exit criterion:** all tests pass; Step 4's equalities hold; `docs/team-sync.md` names the call and its fields; the brief's Q10–Q15 "Hoy" lines updated.

## Alternatives considered

- **Take the case's forecasts and actuals from `eval_results`.** Rejected: the M8 batch stores no `actual_filed_at`, so a cut at D would need its scoring recomputed anyway, and `against_actuals` already does that point-in-time with the same scoring and coded gaps. Step 4 checks the two agree.
- **Compare with the company's usual miss over all quarters.** Rejected: the event quarters would be inside the "usual" set, and a large event miss would raise the yardstick it is measured against. Event studies estimate the normal outcome outside the event window (MacKinlay 1997, §4).
- **Estimate the usual miss only from quarters before the event** (the classic estimation window). Rejected for now: the monthly history starts in 2019-04, so the 2019 and 2020 cases would have almost none. All non-event quarters known by D are used, and the note says so. A pre-event window can be added when the history is longer.
- **Pool the usual miss across companies.** Rejected: the brief asks for the company's own usual miss, and #145 showed companies differ (CAT, XOM).
- **A threshold for thin evidence from Kahneman & Lovallo (1993).** They give no number. The sign-test minimum is a stated, checkable reason; it is a working rule, not a literature value, and the note says what it means.
- **Let the AI pick or rank analogues.** Rejected by the owner (#130) and by Decision 9.

## Files to change

New: `domains/evaluation/past_events.py`, `domains/evaluation/event_metrics.csv`, `tests/evaluation/test_past_events.py`. Changed: `domains/evaluation/__main__.py` (`past-events`), `tests/evaluation/test_cli.py`; at merge `docs/versions.md`, `docs/team-sync.md`, `docs/product/brief.md` (Q10–Q15 "Hoy"), `docs/build-plan.md` (nothing in Section 2: a backlog item), this doc's results.

## Product impact

Serves brief questions 10, 12, 14 and 15 for the cases already in the library, and 13 (n = 0, metrics only). Q11, Q13, Q14 and Q15 still need #147's tags to choose their cases the way the brief describes (a currency, election, supply or inflation case filed under another type); until then the call answers by event type. No existing output, name or field changes; no migration.

Fields of `to_dict`:

- top: `ticker`, `event_type`, `as_of`, `as_of_default`, `rule`, `cases_sha256`, `metrics_sha256`, `n`, `n_listed`, `thin_evidence`, `threshold`, `cases[]`, `same_company_other_type[]`, `metrics[]`, `notes[]`, `missing`;
- a case: `case_id`, `ticker`, `event_date`, `event_type`, `description`, `source_url`, `scope_change`, `same_company`, `same_mechanism`, `direction` (null), `run_id`, `run_as_of`, `reported_quarters`, `quarters[]`;
- a quarter: `period`, `period_end`, `horizon`, `scope_change`, `forecast_margin`, `actual_margin`, `items` {`revenue`, `ebit`} each `forecast`, `actual`, `miss`, `signed_miss`, `miss_unit`, `filings`, `missing`, `usual` (`n_quarters`, `median_miss`, `p90_miss`, `rank`, `beyond_usual`, `missing`) or null;
- a metric: `metric_id`, `metric`, `where_to_find`, `source`, `source_url`;
- misses, margins and ranks are fractions (0.05 is 5%); money is whole currency units, in the run's currency;
- codes the app needs words for: `no_cases`, `thin_evidence`, `few_usual_quarters`, `scope_change`, `unknown_event_type`, and `hindsight`'s `not_reported`, `restated_basis`, `other_ebit_definition`, `zero_base`; notes `rule`, `baseline_only`, `usual_from_monthly_forecasts`, `past_outcomes_not_forecast`, `direction_not_recorded`.

## Where the work stopped

- nov.07.2026: design written; review next.
