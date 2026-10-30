# M3 design: evaluation harness v1 (baseline only)

Status: revised after the Goldfish design review (oct.30.2026) · Elephant: agent team · Branch `m3-evaluation-harness`
Implements Structure Guide Decision 7 and Build Plan M3, including the items "carried to the M3 plan" from the review of M2.

## Problem

Warren can value a company as of any date (v0.2). It cannot yet say how good its forecasts are. Every later milestone, from shocks (M4) to LLM-proposed shocks (M6), has to beat a measured baseline. M3 builds that ruler: it runs the baseline forecast as of historical dates, compares it with what the companies reported afterwards, and stores the error. It also scores a naive forecast, so the baseline itself can be judged.

## What is measured

- **Items:** quarterly revenue and quarterly operating income (EBIT), the two lines news shocks will act on first.
- **Case date and horizon.** A case date is the day the news became public. Facts count as known when their filing's `filed_at` is on or before that day. The run's last actual quarter is the newest quarter whose revenue is known on the case date. Quarter h1 is the next fiscal quarter, and h2–h4 follow it. Each case scores h1 up to its `horizon_quarters` (1–4). Summaries by horizon use whatever cases reach that horizon, and show the count in each cell.
- **Forecast:** the run's `revenue` and `ebit` outputs for those quarters (`run_outputs`, labels like `FY2020Q2`, which are fiscal quarters).
- **Actual:** the value **as first reported** (`get_facts(..., mode="first_reported", frequency="quarterly")`). A restatement years later therefore doesn't count against the forecast. A `restated` flag is never read as "the company restated" (carried item).
  - Forecast and actual are matched on the fiscal label. The actual's `period_end` and its length in days are stored, so 13- and 14-week quarters (AAPL FY2023, JNJ) are visible.
  - **Derived Q4.** When Q4 is not reported on its own, its first-reported value is the 10-K's year minus the first-reported nine months, and its date is the 10-K's `filed_at`. Each such row is flagged `derived`, and results are shown with and without derived quarters. A 10-K recast (for example discontinued operations) lands only in Q4, so the flag makes that visible.
- **Same EBIT definition** (carried item, matters for JNJ and XOM). The actual uses the `ebit` chain in `math_engine.CHAINS`, with the alternative (primary or fallback) that the run's `history:ebit` row for the same quarter a year earlier used. If that alternative isn't reported for the actual quarter, the case fails with a reason and the failure is counted in the summary.

## Benchmarks and metrics

Every forecast is scored next to a **seasonal random walk** (`variant = 'naive_srw'`): the forecast for a quarter is the same quarter a year earlier, as known on the case date (the run's `history:` rows). It is the standard yardstick for quarterly accounting numbers (Foster 1977; Brown & Rozeff 1979). A baseline that can't beat it is worse than doing nothing.

Per case, item, variant and quarter:

- **Revenue:** absolute percentage error, `|forecast − actual| / |actual|`, and the signed version, to show bias. Revenue is never near zero for this universe.
- **EBIT:** error in **margin points**, `|forecast − actual| / actual revenue`, with a signed version. Percentage error on EBIT explodes near zero (Hyndman & Koehler 2006), and EBIT can be near zero or negative (XOM 2020, impairments). Percentage error on EBIT is stored for reference, never summarised.
- **Scaled error (MASE-style):** the baseline's error divided by the naive forecast's error on the same case and quarter. Below 1 means the baseline beat naive.
- **Direction:** the actual direction is the actual against the prior-year comparative **from the same filing** that first reports the actual. That keeps both on one accounting basis, the same-filing principle of D2. JNJ after Kenvue is the case in point. The forecast direction is the forecast against the prior year as known on the case date. A change within ±0.5% counts as flat. The report shows the **base rate** next to the hit rate (the share of actual quarters that rose), because the baseline nearly always forecasts "up" (one growth rate per run).

**Summary** (report and stored batch notes):

- The **headline** is the median error by item and horizon, for the baseline and naive. A small sample of skewed errors makes the mean misleading.
- Next to it: the interquartile range, the share of cases where the baseline beat naive, the direction hit rate with its base rate, and the counts of failed and incomplete cases.
- Event cases and controls are also shown apart, and results with and without scope changes and derived quarters.
- Results by event type are **descriptive only**: about 2 cases per type can't support a conclusion.
- "Beat" in M8 will be a paired, per-case test (sign test or Diebold–Mariano), never a difference of means. M8 decides the test, and M3 stores what it needs.

## Case library (`domains/evaluation/cases.csv`, checked in)

- About 24 cases: 16 events across the eight companies and the event types the Structure Guide lists (guidance, M&A, litigation, regulation, supply chain, macro, restructuring/impairment), plus **8 controls**.
- **Rules fixed before any error is computed.** The case file is committed before the first batch runs, and the batch records the file's SHA-256, so the order can be checked.
  - **Events** are company-specific announcements or market shocks. Each has a source dated on or before the event date. The event date is the day of the public announcement, not the filing date.
  - **Controls** are staggered by rule rather than chosen by looking:
    - Companies in alphabetical order (AAPL, CAT, JNJ, KO, MSFT, PG, WMT, XOM) get control years 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2019.
    - The date is 50 days after the end of the company's fiscal Q2 in that year, so every control sits at the same point in its own reporting cycle.
    - A control is screened against the company's acquisitions, divestitures and guidance withdrawals within 120 days. If one is found, the control moves forward one fiscal quarter, and the reason is recorded.
  - Case dates run from 2019-03-01, the engine's `SUPPORTED_FROM` (carried item). No 2026 KO or XOM cases until their data catch up (carried item).
- Each row records `case_id, ticker, event_date, event_type, description, horizon_quarters, selected_because, source_url, scope_change`. `scope_change` names an acquisition or divestiture that closes inside the horizon, for example MSFT/Activision or KO/BodyArmor. Those errors count, but they're also shown apart.
- Cases are never removed because Warren did badly on them. Removing one is a decision for the owner, recorded in the Structure Guide.
- **Known limitation, stated in the report:** events are chosen in hindsight, as "notable" (Lo & MacKinlay 1990). The controls and the naive benchmark are the check against that.

## Guards (each is a test)

1. **Look-ahead guard (Build Plan M3 test).** Before a case counts, the harness reads every accession number in the run's assumption `method` text, looks up its `filed_at` in `financial_facts` (dates, inclusive), and fails the case if any is after the case date. This is independent of the query code, which already filters by `filed_at`. Market data is outside this guard: its queries already refuse dates after the download and pin the run's downloads (M2.1).
2. **Coverage as a hard error** (carried item). If a case's horizon needs quarters after any company's `history_ends` (today only XOM, 2026-08-03), the case fails instead of warning.
3. **Actual not yet reported.** Such a quarter is stored with status `missing` and never counts as an error of 0. Summaries use only `ok` rows, and the report lists incomplete cases. `eval_failures` is for cases that couldn't be scored at all.
4. **Reproducible.** Each case's run is an ordinary stored run, so `reproduce` and `rebuild` apply. Each batch records the code version, the run ids and the case file's SHA-256.

## Storage (migration `0007_evaluation.sql`)

```sql
eval_cases(case_id TEXT PRIMARY KEY, ticker TEXT, cik TEXT, event_date DATE, event_type TEXT,
           description TEXT, horizon_quarters INTEGER, selected_because TEXT, source_url TEXT,
           scope_change TEXT)
eval_batches(batch_id TEXT PRIMARY KEY, created_at TEXT, code_version TEXT,
             cases_sha256 TEXT, notes TEXT)
eval_results(batch_id TEXT, case_id TEXT, run_id TEXT, variant TEXT,  -- baseline | naive_srw
             item TEXT, period TEXT, horizon INTEGER, period_end DATE, days INTEGER,
             forecast REAL, actual REAL, actual_revenue REAL, comparative REAL,
             prior_year_known REAL, error REAL, signed_error REAL, pct_error REAL,
             direction_forecast INTEGER, direction_actual INTEGER, derived INTEGER,
             actual_method TEXT, status TEXT,                        -- ok | missing
             p10 REAL, p50 REAL, p90 REAL, seed INTEGER,             -- NULL until M4/M8
             PRIMARY KEY (batch_id, case_id, variant, item, period))
eval_failures(batch_id TEXT, case_id TEXT, reason TEXT)
```

`error` is the item's headline error: APE for revenue, margin points for EBIT. This departs from the Build Plan sketch (one row per metric). Here there's one row per forecast, with metrics as columns, plus `eval_batches`. It holds the same information plus what M8 needs, so no second migration is required. `cik` is the company's CIK at the case date, which for XOM is the pinned predecessor.

## Steps

- **Step 0.** This design doc. M3 marked "In progress".
- **Step 1.** Migration 0007, and the case file loader with validation:
  - dates from 2019-03-01
  - tickers in the universe
  - known event types
  - horizon 1–4
  - no duplicates
  - controls on their rule dates

  Tests: the migration applies to an existing database, and malformed rows are refused.
- **Step 2.** `domains/evaluation/harness.py`: actuals (with the EBIT alternative rule and derived-Q4 flags), the naive forecast, the look-ahead and coverage guards, scoring, `evaluate_case`, and batch storage. Tests on Test Corp:
  - errors of about 0, and naive worse than baseline (10% growth)
  - the guard trips on a back-dated filing
  - a missing actual is stored as `missing`
  - a negative EBIT is scored in margin points
  - a derived Q4 is flagged
  - a recast comparative is used for the actual direction
  - an EBIT alternative mismatch fails the case
- **Step 3.** CLI `python -m domains.evaluation run [--case ID ...]`, and a Markdown report at `data/reports/eval/<batch_id>.md`.
  - The report has the headline table and a per-case table (forecast, naive, actual, prior year and the driver rule).
  - It ends with a short glossary of the metrics and the stated limitations.
  - Tests: the CLI end to end on Test Corp.
- **Step 4.** The case library: 16 events with dated sources, and 8 rule-dated controls. The controls' scope screen needs filings data, so a control's final date is confirmed in Step 5.
- **Step 5.** The real batch on the eight companies, the results in the build plan, and M3 marked done when merged. **Blocked** until the cloud environment can reach SEC EDGAR, Yahoo Finance and FRED, and the owner confirms the SEC contact.

Steps 1–4 can merge before Step 5 as an engine-only PR, because they change no existing behaviour.

## Exit criterion (Build Plan)

Baseline error and naive error for every case are computed and saved. The baseline's median errors by horizon are the numbers every later milestone must beat, alongside the naive benchmark.

## Alternatives considered

- **Compare with the latest restated actuals.** Rejected. That scores the forecast against information the company itself didn't have at the time (real-time evaluation, Croushore & Stark 2001).
- **Mean APE as the headline.** Rejected after review. It's undefined near zero, and a few cases dominate it.
- **One fixed date for all controls.** Rejected after review. It's one macro regime, puts each company at a different point in its reporting cycle, and lands on dates with real news, such as XOM/Pioneer closing 2024-05-03.
- **Random dates instead of events.** Rejected for events, because M8 needs real events. Controls use the staggered rule instead.
- **Scoring value per share against the market price.** Never. Warren doesn't predict prices (Structure Guide 1.1, Decision 7).

## Review log

- **Explainer** (13 gaps): quarter alignment, horizon handling, the direction tie, missing data, near-zero APE, the guard's scope, the EBIT rule, derived Q4, case selection and the headline metric. Each is now answered in a section above.
- **Analyst** (5 blockers, all accepted): the controls weren't quiet; the direction used different bases; the direction hit rate shows only the base rate; APE is wrong for EBIT; derived Q4 mixes bases. Ideas taken up: the EBIT governing quarter, `scope_change`, period lengths, case age, a cluster-aware summary, more fixture paths.
- **Professor** (3 blockers, all accepted): no naive benchmark; APE for EBIT; confounded controls. Ideas taken up: nullable p10/p50/p90 columns, descriptive-only type results, a paired test in M8, the hindsight limitation, and a glossary in the report.
- **Not taken:**
  - A cluster bootstrap and Diebold–Mariano, left to M8, which owns the "beat" test.
  - The interval score, left to M8 with the ranges.

## Files

New: `domains/evaluation/{__main__,harness,cases,report}.py`, `domains/evaluation/cases.csv`, `shared_kernel/migrations/0007_evaluation.sql`, `tests/evaluation/test_{cases,harness,cli}.py`.
Changed: `docs/build-plan.md` (status and implementation notes), `docs/versions.md` on merge.
