# M3 design: evaluation harness v1 (baseline only)

Status: draft for Goldfish design review · Elephant: agent team · Branch `m3-evaluation-harness`
Implements Structure Guide Decision 7 and Build Plan M3, including the items "carried to the M3 plan" from the review of M2.

## Problem

Warren can value a company as of any date (v0.2). It cannot yet say how good its forecasts are. Every later milestone, from shocks (M4) to LLM-proposed shocks (M6), has to beat a measured baseline. M3 builds the ruler: run the baseline forecast as of historical dates, compare it with what the companies reported afterwards, and store the error.

## What is measured

- **Items:** quarterly revenue and quarterly operating income (EBIT), the two lines news shocks will act on first.
- **Horizon:** the first 1–4 forecast quarters of a run, which are the quarters after the last quarter reported on the case date.
- **Forecast:** the run's `revenue` and `ebit` outputs for those quarters (`run_outputs`, labels like `FY2020Q2`).
- **Actual:** the value as **first reported** in later filings (`get_facts(..., mode="first_reported", frequency="quarterly")`). Using the first report rather than the latest means a restatement years later doesn't count against the forecast. A `restated` flag is never read as "the company restated" (carried item).
- **Same EBIT definition** for forecast and actual (carried item, matters for JNJ and XOM). The actual uses the same `ebit` chain in `math_engine.CHAINS`, and the alternative it resolves to (primary or fallback) must match the one the run's own `history:ebit` rows used. On a mismatch the case fails with a reason rather than mixing definitions.

## Metrics, per case, item and quarter

- **Absolute percentage error:** `|forecast − actual| / |actual|`.
- **Signed percentage error:** `(forecast − actual) / |actual|`, so a systematic bias shows.
- **Direction hit:** whether the forecast and the actual move the same way against the same quarter a year earlier, taking that quarter's value as known on the case date (the run's `history:` rows). Ties count as "flat" on both sides.
- **Summary** across cases: mean and median APE by item and horizon quarter (h1–h4), share of direction hits, and the same split into event cases and quiet controls.

The M8 metrics (skill score with and without shocks, p10–p90 coverage) are out of scope here. The `variant` column is ready for them.

## Case library (`domains/evaluation/cases.csv`, checked in)

- About 24 cases: 16 events across the eight companies and the event types the Structure Guide lists (guidance, M&A, litigation, regulation, supply chain, macro, restructuring/impairment), plus **8 quiet controls**.
- **Selection rule, written down before any error is computed** so the library can't be tuned to flatter Warren:
  - Events are widely reported company-specific announcements or market shocks. Each has a public source URL in the file, which the analyst review checks.
  - Quiet controls fall on one fixed date for every company, 2024-05-15. No event case falls within 120 days of it. The date was picked by rule, not by looking at results.
  - Case dates run from 2019-03-01, the engine's `SUPPORTED_FROM` (carried item).
  - No 2026 KO or XOM cases until their data catch up (carried item). Cases whose horizon reaches past a company's `history_ends` are refused (see the guards below).
- Each row records `case_id, ticker, event_date, event_type, description, horizon_quarters, selected_because, source_url`. `selected_because` says which rule admitted the case.
- Cases are never removed because Warren did badly on them. Removing one is a decision for the owner, recorded in the Structure Guide.

## Guards (each is a test)

1. **Look-ahead guard (Build Plan M3 test).** Before a case's run counts, the harness reads every accession number in the run's assumption `method` text and looks up its `filed_at` in `financial_facts`. If any is after the case date, the case fails with the accession. This is independent of the query code, which already filters by `filed_at`, so a future bug in that code is caught here.
2. **Coverage as a hard error** (carried item). If a case's horizon needs quarters after a company's `history_ends` (XOM, 2026-08-03), the case fails instead of warning.
3. **Actual not yet reported.** A horizon quarter whose actual isn't in the database yet is recorded as `missing`, never treated as an error of 0. The case counts as complete only when all its quarters have actuals.
4. **Reproducible.** Each case's run is an ordinary stored run, so `reproduce` and `rebuild` apply. Every eval batch records the code version, the run ids and the case file's SHA-256.

## Storage (migration `0007_evaluation.sql`)

```sql
eval_cases(case_id TEXT PRIMARY KEY, ticker TEXT, cik TEXT, event_date DATE, event_type TEXT,
           description TEXT, horizon_quarters INTEGER, selected_because TEXT, source_url TEXT)
eval_batches(batch_id TEXT PRIMARY KEY, created_at TEXT, code_version TEXT,
             cases_sha256 TEXT, notes TEXT)
eval_results(batch_id TEXT, case_id TEXT, run_id TEXT, variant TEXT,      -- 'baseline' for now
             item TEXT, period TEXT, horizon INTEGER, forecast REAL, actual REAL,
             prior_year REAL, ape REAL, signed_error REAL, direction_hit INTEGER,
             actual_method TEXT, status TEXT,                            -- ok | missing
             PRIMARY KEY (batch_id, case_id, variant, item, period))
eval_failures(batch_id TEXT, case_id TEXT, reason TEXT)
```

This departs slightly from the Build Plan sketch (one row per metric). Here there is one row per forecast with the metrics as columns, plus `eval_batches`, so a batch is reproducible as a unit. It's the same information in fewer rows.

## Steps

- **Step 0.** This design doc. Mark M3 "In progress" in the build plan.
- **Step 1.** Migration 0007, and the case file loader with validation (dates, tickers, types, horizon 1–4, no duplicates, controls follow the rule). Tests: the migration applies to an existing database; malformed rows are refused.
- **Step 2.** `domains/evaluation/harness.py`, pure where possible:
  - `actuals()`: first-reported quarterly revenue and EBIT, using the same chain alternative as the run.
  - `guard_look_ahead()`: the guard above.
  - `score()`: APE, signed error, direction.
  - `evaluate_case()`: run, guard, score, store.

  Tests on the synthetic Test Corp: its revenue grows exactly 10% a year, so baseline error is about 0 and every direction is a hit. A filing back-dated after the case date trips the guard. A missing actual is recorded as `missing`. A different EBIT definition fails the case.
- **Step 3.** CLI `python -m domains.evaluation run [--case ID ...]`, plus a Markdown report at `data/reports/eval/<batch_id>.md` with a per-case table and a summary. Tests: the CLI end to end on Test Corp, and the report lists every case and failure.
- **Step 4.** The case library: 16 events and 8 controls with sources.
- **Step 5.** The real batch on the eight companies, the results in the build plan, M3 marked done when merged. **Blocked** until the cloud environment can reach SEC EDGAR, Yahoo Finance and FRED, and the owner confirms the SEC contact. Steps 0–4 don't need data.

## Exit criterion (Build Plan)

Baseline error for every case is computed and saved. This is the number every later milestone must beat. It's met only by Step 5 on real data. Steps 0–4 can merge earlier as v0.3-pre if the data is still blocked, because they change no existing behaviour.

## Alternatives considered

- **Compare with the latest restated actuals.** Rejected. It would score the forecast against information the company itself didn't have at the time, and restatements are rare in this universe anyway (M1.1 audit).
- **Random dates instead of events.** Rejected for events, because M8 needs real events to test shocks. Kept for controls, through the fixed-date rule.
- **Scoring value per share against the market price.** Never. Warren doesn't predict prices (Structure Guide 1.1, Decision 7).
- **Annual instead of quarterly horizons.** Rejected. Shocks land in the first quarters, and annual totals would hide them.

## Files

New: `domains/evaluation/{__main__,harness,cases,report}.py`, `domains/evaluation/cases.csv`, `shared_kernel/migrations/0007_evaluation.sql`, `tests/evaluation/test_{cases,harness,cli}.py`.
Changed: `docs/build-plan.md` (status and implementation notes), `docs/versions.md` on merge.
