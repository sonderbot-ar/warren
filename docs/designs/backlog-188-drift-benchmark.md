# Backlog #188: a benchmark with drift, and a Wilson interval beside the range's record

Issue: https://github.com/sonderbot-ar/warren/issues/188 · Branch `backlog-188-drift-benchmark` · Status: in progress (nov.09.2026).

## Problem

The track record (v0.9.14, `domains/evaluation/track_record.py`, brief Q6) compares Warren with one benchmark, M3's seasonal random walk: the same quarter a year earlier. For a company that grows, that benchmark is wrong by about a year's growth every quarter, so beating it says little. Microsoft's revenue: Warren's median miss 3.9% against the benchmark's 13.8% (`docs/designs/backlog-145-track-record.md`, Results). The professor at the #145 review asked for a fairer second benchmark: Foster's (1977, *The Accounting Review* 52(1):1–21) seasonal random walk **with drift**, the classic time-series benchmark for quarterly accounting numbers.

Second, the range's record per company rests on about 20 calendar-quarter clusters, and a percentile bootstrap undercovers with that few (Efron & Tibshirani 1993, ch. 14; Cameron, Gelbach & Miller 2008 on few clusters). When every actual was inside (`all_inside`), the bootstrap collapses to 100–100% and says nothing at all.

## Plan

- **Step 0.** This design doc and its review. No build plan change (backlog item).
- **Step 1. The drift benchmark, per row and per summary.**
  - Forecast for target quarter t from the origin run's own stored history (the 12 quarters the run read, `math_engine.HISTORY_QUARTERS`, as known on `made_on`): **Q(t−4) + δ**, where δ is the mean of the seasonal changes Q(s) − Q(s−4) over every quarter s in the run's history whose year-earlier quarter is also there (8 changes with 12 quarters: two years of drift). This is Foster's model (his "model 2": E[Q_t] = Q_{t−4} + δ) with δ estimated on the history the forecast had, never on later data. Revenue and EBIT alike, in money. For horizons 1–4, Q(t−4) is always at or before the last reported quarter, so the model needs nothing more.
  - At least 4 changes (one year) are required, else `no_drift` (params `period`, `n_changes`, `min_changes` 4). Q(t−4) missing gives the same `no_benchmark` as M3's benchmark (no forecast at all).
  - Each row item gains `drift`: `forecast` (money), `drift` (δ, money per quarter, year on year), `n_changes`, `miss`, `signed_miss` (positive: the benchmark too high, same scale and unit as Warren's), `closer` (`warren`, `benchmark`, `tie`), `missing`.
  - Each summary gains `drift`: `n_rows` (rows with a drift forecast), `median_miss`, `mean_miss`, `skill` (1 − Warren's mean miss ÷ the drift benchmark's, over the same rows), `wins`, `losses`, `ties`, `sign_p`, `verdict`, `missing`, under exactly the rules of the existing test: all horizons tested once per target quarter, h1 on rows, no verdict at h ≥ 2, none under 12 quarters. The existing benchmark, its fields and the `headline` are unchanged: M3's benchmark stays the headline, since it is the one every past report used.
  - Note `benchmark_with_drift` on every record, saying what the second benchmark is.
  - Tests (`tests/evaluation/test_track_record.py`, synthetic runs): the forecast equals Q(t−4) + mean of the stored seasonal changes; a run holding only rows up to the origin uses nothing later; 3 changes give `no_drift`, 4 do not; a missing Q(t−4) gives `no_benchmark` on both; the drift benchmark is exact on a steady grower (constant δ) and so beats M3's; signed miss and closer; summary counts add up; verdict rules as M3's benchmark's (h ≥ 2 no verdict; per-quarter test); M3's fields are byte-for-byte as before (a test compares `to_dict` less the new keys with a fixed copy). Exit: green.
- **Step 2. A Wilson interval beside the cluster bootstrap.**
  - Each range cell gains `wilson_interval`: the 90% Wilson score interval (z = 1.645, the bootstrap's level) for the share, taking **the number of calendar-quarter clusters as the sample size** (`wilson_n`). Rows in one calendar quarter share one shock, so treating each cluster as one draw is the cautious end (the effective sample size is between the clusters and the rows; Kish 1965 design effect); the bootstrap's interval is shown as before. With every actual inside it gives a real lower bound (with 20 clusters, about 88%), where the bootstrap gave 100–100%. Gaps as the bootstrap's (no rows: None). The verdicts do not change.
  - Tests: Wilson against a hand-computed value; at share 1 the upper end is 1 and the lower is below 1; `wilson_n` equals `n_clusters`; no cell gets one without rows. Exit: green.
- **Step 3. The command and real data.** The text table gains the drift benchmark's median miss and verdict, and each range cell the Wilson interval. On the restored snapshot, as of 2026-11-02 (the #145 results date): every company's drift summary, written below; M3's benchmark figures equal the #145 table; every drift forecast recomputed independently from `assumptions` with SQL equals the call's. Exit: equalities hold.

**Exit criterion:** all tests pass; Step 3's checks hold; `docs/team-sync.md` names the new fields.

## Alternatives considered

- **Drift from the last four changes only.** A one-year drift follows turning points faster but is noisier; Foster's model estimates δ over the history, and the run's stored eight changes are what it had. Not taken.
- **Replace M3's benchmark.** Rejected: every past report and the M8 review score against it, and changing the headline benchmark is a change to how Warren is judged; the drift benchmark sits beside it.
- **A seasonal ARIMA (Brown & Rozeff 1979; Griffin 1977) or analysts' consensus.** Stronger, but ARIMA needs more history than 12 quarters to estimate and consensus is paid data. Not taken.
- **Wilson on rows.** Treats every row as independent: narrower than the bootstrap, so it would not show what few clusters cost. Rejected.

## Files to change

`domains/evaluation/track_record.py`, `tests/evaluation/test_track_record.py`, `tests/evaluation/test_cli.py` (if the text changes a tested line), this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q6 ("¿Qué tan bien ha pronosticado Warren a P&G?") and design principle 4 (show the uncertainty measured). Nothing renamed or removed; no migration; nothing stored. Added fields: row `items.<item>.drift` {`forecast`, `drift`, `n_changes`, `miss`, `signed_miss`, `closer`, `missing`}; summary `drift` {`n_rows`, `median_miss`, `mean_miss`, `skill`, `wins`, `losses`, `ties`, `sign_p`, `verdict`, `missing`}; range cell `wilson_interval` [lo, hi] and `wilson_n`. New codes: `no_drift` (gap), `benchmark_with_drift` (note). Suggested screen: beside "el mismo trimestre del año anterior", a second line "el mismo trimestre del año anterior más su crecimiento medio" (a fairer bar for a growing company); show the Wilson interval when `all_inside` is noted or when `n_clusters` is under about 30.

## Design review

(to come)
