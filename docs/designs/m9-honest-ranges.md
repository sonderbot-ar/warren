# M9 design: honest ranges from the baseline's own past errors

Status: Built, in review (nov.02.2026) · Elephant: agent team · Branch `m9-honest-ranges`
Implements the first item of the Phase 2 direction (Build Plan §4b, owner decision nov.02.2026) and the calibration check of Structure Guide Decision 7 ("do roughly 80% of outcomes fall inside the p10–p90 band?").

## Problem

Warren's p10–p90 band today holds only the uncertainty in the size of the news shocks (M4, `domains/analysis/montecarlo.py:1-7`). The baseline forecast itself is treated as certain: a quarter no shock touches has p10 = p50 = p90. The M8 backtest measured the result: 12–25% of actuals fall inside the AI variants' bands, 0 of 12 for guidance, against the 80% Decision 7 asks for (`docs/phase1-review.md`, "What failed"). Yet the baseline's own errors are the largest errors in Warren: a median 6.1% of revenue and 3.3 margin points of EBIT, with Exxon misses past 100% (`docs/phase1-review.md`, "The baseline is the bigger problem").

M9 gives every revenue and EBIT forecast quarter a range that includes how wrong the baseline has been before, built only from errors that were public on the forecast's date, and tests on held-out dates whether about 80% of actuals land inside. If they don't, M9 says so; nothing is tuned to pass.

What M9 does not do: it does not change the baseline forecast, the shocks, the shock sizes or the value per share. It does not range the valuation (enterprise value, value per share): that needs errors in every driver, not only revenue and EBIT, and is left for later (see Alternatives).

## The method in one paragraph

Run the baseline at many past dates ("origins"), and store how far each forecast quarter was from the actual later reported. At any date D, the errors whose actuals were filed on or before D form an empirical error distribution per forecast horizon. The range for a forecast made at D is the forecast with those past errors applied to it, and its p10 and p90 are the 10th and 90th percentiles. This is the empirical prediction interval of Williams & Goodman (1971, *JASA* 66:752), revisited by Lee & Scholtes (2014, *International Journal of Forecasting* 30:217), and related to the residual-bootstrap intervals of Hyndman & Athanasopoulos (*Forecasting: Principles and Practice*, 3rd ed., §5.5), which resample one-step in-sample residuals where M9 uses errors measured out of sample at each horizon. With an expanding window of past errors it is also a simple form of conformal prediction (Vovk, Gammerman & Shafer 2005, *Algorithmic Learning in a Random World*, ch. 2), whose coverage guarantee needs exchangeable errors; quarterly errors are not exchangeable (they cluster in 2020 and 2022), which is exactly why the held-out test below is the evidence, not the theory. (Conformal's finite-sample guarantee also uses the ⌈(n+1)(1−α)⌉-th order statistic rather than an interpolated percentile; with n ≥ 20 the difference is small and M9 does not claim the guarantee.)

## Definitions

**Origins.** For every company in the universe (`domains/fundamentals/universe.csv`, never a hard-coded list) and the **1st of every month** from 2019-04-01 to 2026-10-01: a baseline run as of that date (`runs.run_baseline`, point-in-time, stored and reproducible like any run). 91 months × 8 companies = 728 origins. The first month is the first full month the engine supports (`math_engine.SUPPORTED_FROM` = 2019-03-01). Monthly origins sample every position between two filings, as case dates do (a case can fall the day after a 10-Q or the day before). Origins use the owner's choices in `user_assumptions.csv`, as the case runs do (`run_baseline` with `choices=None`). An origin whose horizon would reach past the company's `history_ends` (Exxon's filings move to a new CIK on 2026-08-03) keeps the horizons that don't, instead of failing whole (analyst review: failing it whole would drop Exxon's origins from 2025-03 on because of a reorganisation not yet public then). An origin that fails (engine error, an actual reported only under another EBIT definition than the run's own, `harness.first_reported`, or no prior-year history row) is stored as `failed` with its reason and never used; the run's EBIT definition is the one its prior-year history row used (`harness._alternative`), as for cases.

**Horizon.** As in M3: h1 is the first fiscal quarter after the last one reported on the origin date, up to h4 (`harness.evaluate_case`). The actual is the quarter as first reported, on the run's own EBIT definition (`harness.first_reported`).

**Error of one origin, horizon and quarter** (the same units Warren already scores in, made multiplicative for revenue so a range can't go negative):

- Revenue: e_rev = ln(actual revenue / forecast revenue). Undefined if either is ≤ 0; such a row is stored as `excluded` with the reason, and counted. The EBIT row of the same quarter is then `excluded` too: a quarter enters a pool only when both its revenue and its EBIT errors are `ok` (explainer review), so the shared draw below always points at one origin's quarter.
- EBIT: e_ebit = (actual EBIT − forecast EBIT) / actual revenue, in margin points, the M3 unit (the sign is actual minus forecast, so applying it moves a forecast towards the actual).

**Known by D.** An error is known on date D when its actual's `filed_at` (the latest filing among the actual's inputs, `harness.Actual.filed_at`) is on or before D. This is the same rule every fact query uses (`get_facts(..., as_of=D)` keeps `filed_at <= as_of`). Because a run as of the origin date has not seen the filing that reports its h1 actual, `filed_at` is always after the origin, so a known error always comes from an earlier origin. A test pins it: an error filed on D+1 is not used on D.

**Pools** (fixed here, before any result is seen).

- `pooled` (the headline): the errors of all companies known by D, at the same horizon.
- `own` (secondary): the company's own errors known by D, at the same horizon.

A range exists for a horizon only if the pool holds at least **20** known quarter pairs (revenue and EBIT both `ok`) there (`pooled`) or **12** (`own`). Below that, the quarter has no range and is counted as "not enough history", never filled from another pool or horizon. With monthly origins, one company and one horizon add about three errors a quarter (three origins share the same next quarter), so `own` errors are strongly overlapping; the minimums are counts of rows, and the report also shows how many distinct actual quarters stand behind them.

**Applying an error to a forecast** (in `financial_math.py`, with property tests):

- revenue: R = F_rev · exp(e_rev)
- EBIT: E = F_ebit + e_ebit · R, where R is the revenue drawn with it

So an origin's own error applied to its own forecast returns its actual exactly (a property test, to 1e-9 relative).

**Sampling.** N = 10,000 draws per forecast, the M4 sample size. For each horizon, draw N indices uniformly, with replacement, from the known errors in the pool, from one generator per subject and pool, seeded by `range_seed(subject_id, pool)` = the first 15 hex digits of SHA-256(`"range:" + subject + ":" + pool`) as an integer (the form of `harness.case_seed`); horizons draw in order h1 to h4 from that one generator, N indices each. Revenue and EBIT use the **same** index, so a quarter's revenue and margin miss travel together (they are correlated: a revenue shortfall usually comes with a margin shortfall). Horizons are drawn independently; the range is judged per quarter, so the joint shape across quarters does not enter any metric. p10, p50 and p90 are `numpy.percentile` of the N values (linear interpolation, as `montecarlo.simulate_checked`).

**With shocks.** For a shocked variant (`with_shocks`, `llm_named`, `llm_masked`), the formulas above take the i-th **shocked** sample's revenue and EBIT as F_rev and F_ebit (not the baseline's), and apply the i-th drawn error to it. The shocked samples are the ones the M8 simulation drew (same run, same case seed, same N; `montecarlo.sample_lines`), so the M8 bands and p50s stored in `eval_results` are not changed, only read. This assumes the baseline's error is independent of the shocks' size. It is an assumption, stated in the report: when a shock captures a known event, part of the baseline's past error (missed events) is counted twice, so the combined range leans wide. The baseline-only range has no such issue.

## What is tested, on held-out dates

The errors behind a range are always from before its date, so every range below is out of sample by construction. Two tests:

1. **Rolling test (the headline).** Every origin dated **2021-01-01 or later** with its actual known by the batch's `actuals_as_of` gets the baseline-only range built from the errors known on its own date, and is scored. The start date is fixed so that the pooled minimum of 20 is met at every horizon (h4 errors from the first 2019 origins are filed by mid-2020); origins before it are reported as "warm-up" and left out of the headline. At most 8 companies × 70 months × 4 horizons = 2,240 quarters per item, fewer where actuals are not yet reported or origins failed; the report gives the count.
2. **The 26 cases.** The M8 batch's cases, on the same stored runs: the baseline-only range (`baseline`), and the combined range for each shocked variant (`with_shocks`, `llm_named`, `llm_masked`). This is where Warren's actual use lives. Cases dated before about mid-2020 have no pooled range at h4 (12 known h4 pairs on 2020-04-01, 36 on 2020-07-01; analyst check), and they are counted.

**Metrics** (pure functions, with hand-computed tests; the M8 functions reused where they exist, `domains/evaluation/backtest.py`):

- **Coverage**: the share of actuals with p10 ≤ actual ≤ p90 (ends inside, as M8), per item, pool and horizon, and by company. Two intervals around it: the Wilson 95% interval (M8's, assumes independent quarters, which overstates the precision), and a **cluster bootstrap** 90% interval that resamples calendar quarters of the actual (all rows whose actual is the same calendar quarter move together, because they share a macro surprise: 2020 Q2 is one cluster), 10,000 draws, seed `20261102`; the calendar quarter is that of the actual's `period_end` (stored, so WMT's quarter ending 2020-04-30 is 2020 Q2). A sensitivity line uses a moving-block bootstrap over calendar quarters, blocks of 4 (Künsch 1989, *Annals of Statistics* 17:1217), because one origin's miss carries from h1 to h4 across neighbouring quarters (professor review). Also the share below p10 and above p90, so a miss can be told apart as too narrow or off-centre.
- **By company, by horizon, by calendar year** (the hit share over time, so misses that cluster in 2020 and 2022 show), and **h1 split** into quarters that had already ended on the forecast date and quarters still running (analyst review: 46% of h1 rows had ended).
- **Interval score** at α = 0.2, both items divided by actual revenue (M8's `interval_score`, so EBIT is in margin points), against the M8 band on the same quarters, so "wider and better" can be told apart from "just wider".
- **Width**: the median of (p90 − p10) / p50 for revenue and (p90 − p10) / revenue p50 for EBIT, so a reader sees the price of coverage.

**The pass rule** (fixed now; per item, over all four horizons together, pooled baseline-only range, rolling test):

- **met on average** when coverage is between 70% and 90% *and* the cluster bootstrap 90% interval includes 80%;
- **met for every company** when, in addition, each company's coverage is between 65% and 95% (analyst review: pooling can average a far-too-wide range for Walmart with a far-too-narrow one for Exxon; median absolute log revenue error in batch `eval_2026-11-02_1` is 0.035 for WMT and 0.358 for XOM);
- **inconclusive** when the interval includes 80% but coverage is outside 70–90% (with about 22 calendar-quarter clusters the interval is wide, and "includes 80%" alone would read noise as calibration; professor review);
- **failed** otherwise, with whether the range is too narrow (coverage below) or too wide (above).

The same verdict is shown per horizon and for `own`, as information. The 26 cases are reported with the same numbers but are too few to pass or fail on their own. A failed check is a valid result, reported as such; neither the percentiles, the pools, the minimums nor the start date are changed after results are seen. Any change is a new version with a new design note.

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
- The report: the pass rule and its result first, per item; coverage by pool, horizon and company; below-p10 and above-p90 shares; width; interval score against the M8 bands on the cases; the warm-up and "not enough history" counts; the limitations (overlapping origins, errors that cluster in crises, independence of shock and baseline error, revenue and EBIT only, no valuation range; one-off GAAP charges such as P&G's FY2019Q4 Gillette impairment, Exxon's FY2020Q4 impairment and J&J's FY2023Q1 talc charge sit in the EBIT tails, counted about three times each by monthly origins; scope changes such as Kenvue's move to discontinued operations in 2023 score as misses; 14-week quarters such as AAPL FY2023Q1). Christoffersen tests and coverage net of special items are backlog items (#123, #116); adaptive windows are #122.

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
- **Adaptive or recency-weighted windows** (Gibbs & Candès 2021, adaptive conformal inference; Barber et al. 2023, *Annals of Statistics* 51:816). Better suited to errors that drift, but each adds a tuning constant; M9 tests the plain expanding window first, and these become a backlog item to test on the same origins.
- **Origins before 2019.** Facts exist from 2006, but the engine is supported from 2019-03-01 (three full FY2016+ years behind it, M2 exit criterion). Moving that date is an engine change with its own gap checks; not in M9. It is the natural way to get more history later.
- **Only origins on filing days** (the day after each 10-Q). Fewer, less overlapping rows, but cases are not on filing days, and h1 then always starts a month into the quarter. Monthly origins match how cases are spread.
- **Scale `pooled` errors by each company's own volatility.** Would stop Exxon's misses widening Procter & Gamble's range; needs a volatility estimate that is itself point-in-time and noisy. `own` is the simple version of the same idea; the report shows coverage by company so the cost of pooling is visible.

## Files to change

`docs/designs/m9-honest-ranges.md`, `docs/build-plan.md`; `domains/analysis/financial_math.py`; `shared_kernel/migrations/0017_ranges.sql`; new `domains/evaluation/ranges.py`, `domains/evaluation/ranges_report.py`; `domains/evaluation/__main__.py` (the `ranges` commands); `domains/evaluation/harness.py` (the actual's filing date in each row; a shorter horizon for origins near `history_ends`); `domains/analysis/montecarlo.py` (`sample_lines`); `docs/structure-guide.md` (a status note on Decision 7 at merge, no change to the decision); tests under `tests/evaluation/`, `tests/analysis/` and `tests/shared_kernel/`.

## Design review (nov.02.2026)

Explainer, analyst and professor, in parallel; no blockers from the analyst or the professor. Accepted: pairs only (explainer B1); the shocked sample as the base (B2); failed origins and the EBIT definition named (B3); the exact seed and one generator (I1); the owner's choices (I2); the expected count (I4); EBIT interval score in margin points (I5); `period_end` stored as the cluster key (analyst 5); a stricter pass rule with a point band, per-company check and "inconclusive" (analyst 1 and 6, professor 1); the moving-block sensitivity (professor 2); coverage by year and the h1 split (professor 3 and 5, analyst 4); shorter horizons instead of a failed Exxon origin (analyst 7); the h4-only warm-up wording (analyst 8); FPP3 wording and the conformal quantile note (professor). To the backlog: adaptive conformal windows (#122); coverage net of special items, scope-change flags and Christoffersen tests (#123, with #116). Not taken: the explainer's I8 (whether "Phase 2" means the LatAm platform): the owner named this Phase 2 focus on nov.02.2026 (Build Plan §4b).

## Results (build `ranges_2026-11-02_1`, nov.02.2026)

Run on the restored snapshot (`warren-20261102T002927Z`): 728 origins, 718 built and 10 failed (Exxon from 2026-01-01: even one quarter reaches past its filings' 2026-08-03 cut-off). 5,410 error rows; the rolling test scores 2,033 quarters per item (pooled). `ranges reproduce --build ranges_2026-11-02_1` checks 5,410 errors and 12,456 ranges: OK. Report: `data/reports/eval/ranges_2026-11-02_1_ranges.md` (in the data snapshot, not in git).

**The pass rule** (rolling test, pooled, baseline range, all horizons):

| Item | Coverage | Cluster bootstrap 90% | Block bootstrap 90% | Below p10 / above p90 | Verdict |
|---|---|---|---|---|---|
| Revenue | 83.1% | 78.5% to 87.2% | 76.3% to 88.8% | 8.9% / 8.0% | **met on average**, not for every company |
| EBIT | 84.8% | 80.8% to 88.6% | 81.3% to 88.3% | 7.0% / 8.1% | **failed: too wide** (by under one point) |

- **Pooling hides the companies.** Pooled revenue coverage is 100% for Microsoft, P&G and Walmart, 23.4% for Exxon and 70.9% for Caterpillar; EBIT is 100% for Walmart and 37.8% for Exxon. Exactly the analyst's warning: on average it lands, for no single company is it right. The ranges are wide for that reason: median width 38.9% of revenue and 18.3 margin points of EBIT.
- **The company's own errors** (`own`, information only) are closer per company and narrower: revenue 75.3% (69.7% to 80.6%), EBIT 78.7% (71.8% to 84.9%), median width 23.0% of revenue and 17.1 margin points; but P&G's revenue falls to 58.4%, and 11 quarters have no range.
- **By horizon** coverage is flat (revenue 81–85%, EBIT 83–86%). An h1 quarter that had already ended on the forecast date is covered a little less (revenue 79.0%, against 85.3% for a quarter still running).
- **By year** it is not flat: revenue actuals in 2021 are covered 56.8% of the time (43% above p90: the rebound came after a window full of 2020 misses), 2024 77.7%, 2026 96.0%.
- **Warm-up** origins (2019–2020, information only): 66.8% revenue, 72.0% EBIT.

**The 26 cases** (pooled, against M8 on the same quarters):

| Variant | Item | Quarters with a range | Coverage now | In M8 | Interval score now | In M8 |
|---|---|---|---|---|---|---|
| Baseline | Revenue | 77 | 79.2% | 0% | 0.860 | 1.239 |
| Baseline | EBIT | 77 | 87.0% | 0% | 0.380 | 0.534 |
| AI, masked | Revenue | 53 | 75.5% | 13.2% | 1.068 | 1.331 |
| AI, masked | EBIT | 53 | 84.9% | 20.8% | 0.405 | 0.517 |
| AI, named | Revenue | 48 | 75.0% | 16.7% | 1.088 | 1.370 |
| AI, named | EBIT | 48 | 83.3% | 22.9% | 0.413 | 0.511 |
| Guidance | Revenue / EBIT | 4 | 100% / 100% | 0% / 0% | 0.479 / 0.225 | 0.631 / 0.231 |

27 baseline quarters (mostly 2019–2020 cases at h3–h4) have no range: not enough history yet. The interval score is lower (better) in every row, so the new ranges are not just wider: they are better ranges.

**What it means.** Warren now has a range that includes its own error, and on held-out dates it covers about 80% of outcomes on average, which Decision 7 asks for: met for revenue, a hair too wide for EBIT. It is not calibrated per company: pooling borrows Exxon's misses for Walmart and the other way round. The next steps that follow from this (scaling pooled errors per company, adaptive windows #122, special items #123) are backlog items, not changes to this build; the pass rule is not moved after the fact.
