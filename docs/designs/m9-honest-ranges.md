# M9 design: honest ranges from the baseline's own past errors

Status: In progress (nov.02.2026) · Elephant: agent team · Branch `m9-honest-ranges`
Implements the first item of the Phase 2 direction (Build Plan §4b, owner decision nov.02.2026) and the calibration check of Structure Guide Decision 7 ("do roughly 80% of outcomes fall inside the p10–p90 band?").

## Problem

Warren's p10–p90 band today holds only the uncertainty in the size of the news shocks (M4, `domains/analysis/montecarlo.py:1-7`). The baseline forecast itself is treated as certain: a quarter no shock touches has p10 = p50 = p90. The M8 backtest measured the result: 12–25% of actuals fall inside the AI variants' bands, 0 of 12 for guidance, against the 80% Decision 7 asks for (`docs/phase1-review.md`, "What failed"). Yet the baseline's own errors are the largest errors in Warren: a median 6.1% of revenue and 3.3 margin points of EBIT, with Exxon misses past 100% (`docs/phase1-review.md`, "The baseline is the bigger problem").

M9 gives every revenue and EBIT forecast quarter a range that includes how wrong the baseline has been before, built only from errors that were public on the forecast's date, and tests on held-out dates whether about 80% of actuals land inside. If they don't, M9 says so; nothing is tuned to pass.

What M9 does not do: it does not change the baseline forecast, the shocks, the shock sizes or the value per share. It does not range the valuation (enterprise value, value per share): that needs errors in every driver, not only revenue and EBIT, and is left for later (see Alternatives).

## The method in one paragraph

Run the baseline at many past dates ("origins"), and store how far each forecast quarter was from the actual later reported. At any date D, the errors whose actuals were filed on or before D form an empirical error distribution per forecast horizon. The range for a forecast made at D is the forecast with those past errors applied to it, and its p10 and p90 are the 10th and 90th percentiles. This is the empirical prediction interval of Williams & Goodman (1971, *JASA* 66:752), revisited by Lee & Scholtes (2014, *International Journal of Forecasting* 30:217), and the "forecast with past residuals" interval of Hyndman & Athanasopoulos (*Forecasting: Principles and Practice*, 3rd ed., §5.5). With an expanding window of past errors it is also a simple form of conformal prediction (Vovk, Gammerman & Shafer 2005, *Algorithmic Learning in a Random World*, ch. 2), whose coverage guarantee needs exchangeable errors; quarterly errors are not exchangeable (they cluster in 2020 and 2022), which is exactly why the held-out test below is the evidence, not the theory.

## Definitions

**Origins.** For every company in the universe (`domains/fundamentals/universe.csv`, never a hard-coded list) and the **1st of every month** from 2019-04-01 to 2026-10-01: a baseline run as of that date (`runs.run_baseline`, point-in-time, stored and reproducible like any run). 91 months × 8 companies = 728 origins. The first month is the first full month the engine supports (`math_engine.SUPPORTED_FROM` = 2019-03-01). Monthly origins sample every position between two filings, as case dates do (a case can fall the day after a 10-Q or the day before). An origin that fails (engine error, coverage past `history_ends`, e.g. Exxon after 2026-08-03) is stored with its reason and never used.

**Horizon.** As in M3: h1 is the first fiscal quarter after the last one reported on the origin date, up to h4 (`harness.evaluate_case`). The actual is the quarter as first reported, on the run's own EBIT definition (`harness.first_reported`).

**Error of one origin, horizon and quarter** (the same units Warren already scores in, made multiplicative for revenue so a range can't go negative):

- Revenue: e_rev = ln(actual revenue / forecast revenue). Undefined if either is ≤ 0; such a row is stored as `excluded` with the reason, and counted.
- EBIT: e_ebit = (actual EBIT − forecast EBIT) / actual revenue, in margin points, the M3 unit (the sign is actual minus forecast, so applying it moves a forecast towards the actual).

**Known by D.** An error is known on date D when its actual's `filed_at` (the latest filing among the actual's inputs, `harness.Actual.filed_at`) is on or before D. This is the same rule every fact query uses (`get_facts(..., as_of=D)` keeps `filed_at <= as_of`). Because a run as of the origin date has not seen the filing that reports its h1 actual, `filed_at` is always after the origin, so a known error always comes from an earlier origin. A test pins it: an error filed on D+1 is not used on D.

**Pools** (fixed here, before any result is seen).

- `pooled` (the headline): the errors of all companies known by D, at the same horizon.
- `own` (secondary): the company's own errors known by D, at the same horizon.

A range exists for a horizon only if the pool holds at least **20** known errors there (`pooled`) or **12** (`own`). Below that, the quarter has no range and is counted as "not enough history", never filled from another pool or horizon. With monthly origins, one company and one horizon add about three errors a quarter (three origins share the same next quarter), so `own` errors are strongly overlapping; the minimums are counts of rows, and the report also shows how many distinct actual quarters stand behind them.

**Applying an error to a forecast** (in `financial_math.py`, with property tests):

- revenue: R = F_rev · exp(e_rev)
- EBIT: E = F_ebit + e_ebit · R, where R is the revenue drawn with it

So an origin's own error applied to its own forecast returns its actual exactly (a property test, to 1e-9 relative).

**Sampling.** N = 10,000 draws per forecast, the M4 sample size. For each horizon, draw N indices uniformly, with replacement, from the known errors in the pool, from a generator seeded by `range_seed(subject_id, pool)` (SHA-256 of `"range:" + subject + ":" + pool`, as `harness.case_seed` does). Revenue and EBIT use the **same** index, so a quarter's revenue and margin miss travel together (they are correlated: a revenue shortfall usually comes with a margin shortfall). Horizons are drawn independently; the range is judged per quarter, so the joint shape across quarters does not enter any metric. p10, p50 and p90 are `numpy.percentile` of the N values (linear interpolation, as `montecarlo.simulate_checked`).

**With shocks.** For a shocked variant (`with_shocks`, `llm_named`, `llm_masked`), sample i is the i-th shocked sample of the M4/M8 simulation (same run, same case seed, same N, so the M8 p50 is untouched) with the i-th drawn baseline error applied to it. This assumes the baseline's error is independent of the shocks' size. It is an assumption, stated in the report: when a shock captures a known event, part of the baseline's past error (missed events) is counted twice, so the combined range leans wide. The baseline-only range has no such issue.

## What is tested, on held-out dates

The errors behind a range are always from before its date, so every range below is out of sample by construction. Two tests:

1. **Rolling test (the headline).** Every origin dated **2021-01-01 or later** with its actual known by the batch's `actuals_as_of` gets the baseline-only range built from the errors known on its own date, and is scored. The start date is fixed so that the pooled minimum of 20 is met at every horizon (h4 errors from the first 2019 origins are filed by mid-2020); origins before it are reported as "warm-up" and left out of the headline. About 8 companies × 70 months × up to 4 horizons ≈ 2,000 quarters per item.
2. **The 26 cases.** The M8 batch's cases, on the same stored runs: the baseline-only range (`baseline`), and the combined range for each shocked variant (`with_shocks`, `llm_named`, `llm_masked`). This is where Warren's actual use lives. Cases dated before about mid-2020 have no range at h3–h4 (not enough history), and they are counted.

**Metrics** (pure functions, with hand-computed tests; the M8 functions reused where they exist, `domains/evaluation/backtest.py`):

- **Coverage**: the share of actuals with p10 ≤ actual ≤ p90 (ends inside, as M8), per item, pool and horizon, and by company. Two intervals around it: the Wilson 95% interval (M8's, assumes independent quarters, which overstates the precision), and a **cluster bootstrap** 90% interval that resamples calendar quarters of the actual (all rows whose actual is the same calendar quarter move together, because they share a macro surprise: 2020 Q2 is one cluster), 10,000 draws, seed `20261102`. Also the share below p10 and above p90, so a miss can be told apart as too narrow or off-centre.
- **Interval score** at α = 0.2, scaled by actual revenue (M8's `interval_score`), against the M8 band on the same quarters, so "wider and better" can be told apart from "just wider".
- **Width**: the median of (p90 − p10) / p50 for revenue and (p90 − p10) / revenue p50 for EBIT, so a reader sees the price of coverage.

**The pass rule** (fixed now). Decision 7's check is **met** for an item in the rolling test when the cluster bootstrap 90% interval of pooled baseline-only coverage includes 80%. Otherwise it **fails**, and the report says whether the range is too narrow (coverage below) or too wide (above). The 26 cases are reported with the same numbers but are too few to pass or fail on their own. A failed check is a valid result, reported as such; neither the percentiles, the pools, the minimums nor the start date are changed after results are seen. Any change is a new version with a new design note.

## Storage and reproducibility

Migration `0017_ranges.sql` (new tables only; no stored row changes, so the migration test is that every existing table and row is untouched on a v16 database):

- `forecast_origins` (origin_id, ticker, as_of, run_id NULL, status `ok` or `failed`, reason)
- `baseline_errors` (run_id, ticker, origin_date, horizon, period, item, forecast, actual, actual_revenue, actual_filed_at, error, status `ok` / `missing` / `excluded`, reason), one row per origin, horizon and item; `actuals_as_of` of the build in `range_builds`.
- `range_builds` (build_id, code_version, actuals_as_of, origins_sha256) and `range_results` (build_id, subject_kind `origin` or `case`, subject_id, run_id, variant, pool, item, period, horizon, n_errors, n_quarters, p10, p50, p90, actual, inside, seed, status `ok` / `no_history` / `missing`).

`python -m domains.evaluation ranges reproduce --build B` recomputes every error from the stored runs and the first-reported actuals as of the build's `actuals_as_of`, and every range from them and its seed, and checks forecasts, actuals and percentiles to the cent (0.005 currency units) and errors to 1e-9. Tests: a stored build reproduces; an edited error or an edited percentile fails it.

## Commands and report

- `python -m domains.evaluation ranges origins [--ticker T ...] [--from D] [--to D]`: builds the origin runs and their errors (skips an origin already stored with the same code version; a failed origin is stored with its reason).
- `python -m domains.evaluation ranges test [--batch EVAL_BATCH]`: the rolling test and, given an M8 batch, the 26 cases; writes `data/reports/eval/<build_id>_ranges.md`.
- `python -m domains.evaluation ranges reproduce --build B`.
- The report: the pass rule and its result first, per item; coverage by pool, horizon and company; below-p10 and above-p90 shares; width; interval score against the M8 bands on the cases; the warm-up and "not enough history" counts; the limitations (overlapping origins, errors that cluster in crises, independence of shock and baseline error, revenue and EBIT only, no valuation range).

## Steps

- **Step 0.** This design doc; M9 and M10 rows in the build plan (M9 In progress).
- **Step 1.** `financial_math.apply_revenue_error`, `apply_margin_error` and `log_ratio` with property tests (round trip to the actual; R > 0 for any finite error; monotone in the error). Migration 0017 and its test on a v16 database. `domains/evaluation/ranges.py`: `origin_errors(conn, ticker, as_of, actuals_as_of)` stores an origin's run and its error rows, reusing `harness.first_reported`; tests on Test Corp (a known actual gives the hand-computed error; a missing actual is `missing`; a negative revenue is `excluded`; an origin past `history_ends` is `failed` with its reason).
- **Step 2.** The range: `known_errors(conn, d, horizon, pool, ticker)` (known-by filter), `baseline_range` and `combined_range` (sampling above), `range_seed`. Tests: an error filed on D+1 is not used on D, one filed on D is; below the minimum gives `no_history`; the same seed gives the same percentiles; a pool of one repeated error gives p10 = p50 = p90 = the actual; with zero-width shocks the combined range equals the baseline range; revenue and EBIT use the same draw.
- **Step 3.** Metrics (coverage with below/above shares, cluster bootstrap, width; M8 functions reused), the `ranges` commands, the report and `reproduce`. Tests: hand-made rows with hand-computed coverage and bootstrap behaviour (all rows in one cluster gives a degenerate interval); the CLI end to end on Test Corp; reproduce passes, and fails on an edited error and an edited percentile.
- **Step 4.** The real run on the restored snapshot (CLAUDE.md, Data): all origins, the rolling test, the 26 cases on batch `eval_2026-11-02_1`; results written below; the reproduce check; snapshot saved.

**Exit criterion:** the report exists with the pass rule's result per item (met or failed, with its interval), the 26 cases' coverage beside M8's, and `ranges reproduce` passes on the stored build.

## Alternatives considered

- **Sample the baseline's drivers** (growth, margin, capex) inside the Monte Carlo from their historical spread. It would range the valuation too, but the drivers' spread is not the forecast's error: the baseline's biggest misses (Exxon 2020, Coca-Cola refranchising) are model misses, not driver noise. Errors measured against actuals are what Decision 7 checks. Left for a later milestone that ranges the valuation.
- **A parametric band** (normal or Student-t with the errors' standard deviation). Errors are skewed and fat-tailed (Exxon's 2020 misses), so a normal band would misplace p10 and p90; the empirical quantiles need no shape. Kept as a possible sensitivity line, not built.
- **Quantile regression on company features** (sector, volatility). More precise per company, but with 8 companies and about six years of errors it would be fitted to the noise. `own` shows how far company-specific ranges get on their own.
- **Origins before 2019.** Facts exist from 2006, but the engine is supported from 2019-03-01 (three full FY2016+ years behind it, M2 exit criterion). Moving that date is an engine change with its own gap checks; not in M9. It is the natural way to get more history later.
- **Only origins on filing days** (the day after each 10-Q). Fewer, less overlapping rows, but cases are not on filing days, and h1 then always starts a month into the quarter. Monthly origins match how cases are spread.
- **Scale `pooled` errors by each company's own volatility.** Would stop Exxon's misses widening Procter & Gamble's range; needs a volatility estimate that is itself point-in-time and noisy. `own` is the simple version of the same idea; the report shows coverage by company so the cost of pooling is visible.

## Files to change

`docs/designs/m9-honest-ranges.md`, `docs/build-plan.md`; `domains/analysis/financial_math.py`; `shared_kernel/migrations/0017_ranges.sql`; new `domains/evaluation/ranges.py`, `domains/evaluation/ranges_report.py`; `domains/evaluation/__main__.py` (the `ranges` commands); tests under `tests/evaluation/`, `tests/analysis/` and `tests/shared_kernel/`.

## Results

Not run yet.
