# Backlog #144: the error range and its track record on any run

Issue: https://github.com/sonderbot-ar/warren/issues/144 · Branch `backlog-144-run-ranges` · Version v0.9.8 when merged.

## Problem

The front-end team's request R3 (brief question 5, `docs/product/brief.md` §5; design principle 4: every forecast shows the uncertainty the engine measures). M9 (v0.9) gives each forecast quarter a p10–p90 range from the baseline's own past misses, but only for the 728 stored monthly origins and the backtest cases (`domains/evaluation/ranges.py`, `build_rows`). A run made today, or any run F2's first screen shows, has no range. And the one coverage figure M9 reports (revenue 83.1% pooled) hides that 4 of 8 companies fell outside 65–95% (v0.9 row of `docs/versions.md`), so a student must see how the range did on this company too.

## What changes

A new call, `domains.evaluation.run_ranges.run_ranges(conn, run_id, n=10_000) -> RunRanges`, and a command, `python -m domains.evaluation ranges run --run-id R [--json]`. For one stored run, as of its own date D:

1. **The range per forecast quarter.** For horizons 1–4, the M9 method unchanged (`ranges.ranges` on `ranges.constant_samples` of the run's own quarterly revenue and EBIT outputs): the misses whose actual was filed on or before D (`ranges.known`), both pools (`pooled`: all companies; `own`: this company), n draws, one generator per pool seeded `ranges.range_seed(f"{run_id}:baseline", pool)`, as M9 seeds its subjects (`ranges.py:subject_rows`). Each band carries `p10`, `p50`, `p90`, `n_errors`, `n_quarters`. A pool with fewer known misses than M9's minimum (`MIN_ERRORS`: 20 pooled, 12 own) has no band and the code `no_history` (params `horizon`, `pool`, `n_errors`, `min_errors`). Quarters 5–8 have no band and the code `beyond_horizon` (params `horizon`, `max_horizon` 4): M9 measured misses for the first four quarters only.
2. **How the range has done so far (coverage).** Per pool, per item, over all companies and over this company: how many past quarters fell inside their p10–p90, below and above, the share and its Wilson 95% interval (`backtest.wilson`, as M9's report). The quarters counted are M9's rolling test, cut at D: baseline ranges of the stored origins dated `ROLLING_FROM` (2021-01-01) or later and **before D**, each built as M9 builds it (from the misses known on the origin's own date, seeded by its origin id), scored only where that quarter's actual (the item's `actual_filed_at`) was filed on or before D. Horizons 1–4 are counted together, as M9's headline does. A cell with fewer than 20 scored quarters still shows its counts and gets the code `few_scored` (params `n`, `min_scored` 20); a run dated before 2021 has none and gets `no_coverage_history`.
3. **What the range is of.** `basis` is `"baseline"`: the range is the baseline's own error, not the shocks. A note says so (`baseline_only`). The shocked range on a pipeline run (M9's "on top of the simulation") is not built here; see Alternatives.
4. **What it rests on.** `errors_sha256` (`ranges.pairs_sha256` of the misses known on D, so a caller can tell if the stored history behind a range has changed since), `errors_filed_to` (the newest filing date among them) and `currency` (`montecarlo._currency`, the revenue concepts' unit; Decision 11, explicit currency).

All values are raw and unrounded, in the run's currency; EBIT's band is in money (M9 applies the margin error on the drawn revenue, `fm.apply_margin_error`). Gaps are coded (`reported.Coded`: `code`, `params`, `text` in English), never raised, so the app always gets an answer. A run that is not stored raises, as `against_actuals` does.

**Point in time.** Everything comes from data public by D: the misses (filed by D), the origins scored for coverage (dated before D, their actuals filed by D, their ranges from misses filed by their own date). Nothing is written. The run's own forecast is the stored run's output, which already reads only data public by D. Tests in Step 1 check the D boundary for both the bands and the coverage.

**Same numbers as M9.** For a stored origin's own run, the call's bands with the origin's id as the seed key equal the stored M9 build's rows exactly, and its coverage cut at the build's date equals the M9 report's rolling coverage on the same rows (Step 3, real data). Computing the 718 origin ranges takes about 5 seconds (measured on the restored data, nov.03.2026); the call computes only those dated before D.

## Steps

- **Step 0.** This design doc; no build plan change (a backlog item).
- **Step 1.** `domains/evaluation/run_ranges.py` with `run_ranges`, `RunRanges.to_dict`, and the coverage helper `coverage(conn, ticker, on, pairs, n)`. Tests (`tests/evaluation/test_run_ranges.py`, synthetic `baseline_errors` and `forecast_origins` rows in a migrated test database plus a stored run, numbers known by construction): the bands equal `ranges.ranges` called directly with the same seed; a miss filed on D is used and one filed the day after is not; quarters 5–8 are `beyond_horizon`; 19 pooled misses give `no_history` and 20 give a band; the own pool counts only the company's misses; coverage counts an origin dated D−1 but not one dated D, and a quarter filed after D is not counted; inside/below/above sum to n; a cell with 19 quarters is `few_scored`; a run before 2021 is `no_coverage_history`; the same call twice gives the same dict; `to_dict` round-trips through `json`; an unknown run raises. Exit: green.
- **Step 2.** The command `ranges run --run-id R [--json]`: a table per pool of p10 / p50 / p90 per quarter in millions, the coverage lines, the notes; `--json` prints `to_dict` only. Tests (`tests/evaluation/test_cli.py`): text output names the basis, the pools and the coverage; `--json` is plain JSON with the fields below; an unknown run exits 1 with a message. Exit: green; ruff clean.
- **Step 3.** Real data, on the restored snapshot: on every stored origin run, the bands with the origin id as seed key equal the `ranges_2026-11-02_1` rows (all 11,416); coverage cut at 2026-11-02 equals the M9 rolling coverage from the stored rows (pooled and per company); one run per company as of 2026-11-02 (the latest ended day the data holds) gets bands and coverage, written below with the timing. `python -m domains.evaluation ranges reproduce` still passes. Exit: equalities hold.

**Exit criterion:** all tests pass; Step 3's equalities hold; `docs/team-sync.md` names the call and its fields.

## Alternatives considered

- **Read the ranges from a stored M9 build.** Rejected: a build covers only origins and cases, and its coverage is cut at the build's date, not the run's. Computing on the call gives the same numbers (Step 3) and works for any run and date.
- **Put the range in the pipeline report now.** Deferred: a report is compared again by `reproduce`, and the range moves when the stored misses are scored again (new actuals filed). It needs the misses' hash in the pipeline state first. Filed as a backlog item; the app gets the range from the call.
- **The shocked range on pipeline runs.** Deferred to the same item: it needs the pipeline's simulation samples again (`montecarlo.sample_lines` with the stored seed and shocks), and the front-end's first screen asks for the baseline's range first (brief Q5).
- **Coverage per horizon.** Not now: at h4 a company has about 20 scored quarters since 2021, too few for a share to mean much. The pooled-horizon figure is M9's headline; per horizon can come with #125 (scaling by each company's volatility).
- **Store the range with each run.** Rejected: it would add a table whose rows go stale when misses are rescored; the call is deterministic and cheap.

## Files to change

New: `domains/evaluation/run_ranges.py`, `tests/evaluation/test_run_ranges.py`. Changed: `domains/evaluation/__main__.py` (`ranges run`), `tests/evaluation/test_cli.py`; at merge `docs/versions.md`, `docs/team-sync.md`, `docs/product/brief.md` (Q5's "Hoy" line).

## Product impact

Serves brief question 5 (the forecast with its range) and design principle 4. Q5's "Hoy" line changes from "En parte … not for a new run. Request R3 (#144)" to say the range and the company's coverage exist for any run, the baseline's only (the shocked range still waits). No existing output, name or field changes.

Adds `domains.evaluation.run_ranges.run_ranges(conn, run_id)` and `to_dict`, and the command `ranges run`. Fields of `to_dict`:

- top: `run_id`, `ticker`, `as_of`, `currency`, `basis` (`"baseline"`), `n_samples`, `errors_sha256`, `errors_filed_to`, `quarters[]`, `coverage[]`, `notes[]` (codeds);
- a quarter: `period` (the run's label, e.g. `FY2026Q3`), `horizon` (1–8), `revenue_forecast`, `ebit_forecast`, `bands[]`;
- a band: `pool` (`pooled` or `own`), `n_errors`, `n_quarters`, `revenue` and `ebit` (each `{p10, p50, p90}` or None), `missing` (a coded or None);
- a coverage cell: `pool`, `scope` (`all` or `company`), `item`, `inside`, `below`, `above`, `n`, `share`, `interval` (`[low, high]`, Wilson 95%, or None), `origins_from` (2021-01-01), `missing` (a coded or None);
- codes: `no_history`, `beyond_horizon`, `few_scored`, `no_coverage_history`, `baseline_only`.
