# Backlog #201 design: list a run's simulations with their variant

Issue #201 (front-end, from the #167 design review, `docs/designs/backlog-167-shocked-range.md`, Product impact). Branch `backlog-201-run-simulations`.

Status: In progress (nov.05.2026).

## Problem

The shocked range (v0.9.16, `run_ranges(conn, run_id, sim_id=S)`) needs a simulation id, but the app holds a run id. The `simulations` table (`shared_kernel/migrations/0008_shocks.sql`) has no column for which news variant a simulation stands for: named (the AI read the company's name), masked (the name hidden; M8's headline variant), or neither (manual or guidance shocks). Today the only way from a run to "its masked simulation" is a pipeline's checkpoint (`graph.final_state(...).sim[variant].sim_id`), which the app should not read (design principle 5: the app does no lookups through internals). A run can also have several simulations: one per variant, M8's backtest ones, and any made by hand.

## What the call answers

`domains.orchestration.simulations.run_simulations(conn, run_id, check=False)` returns, for one stored run:

- `run_id`, `ticker`, `as_of`, `currency`.
- `simulations[]`, one per row of `simulations` with this `run_id`, each with:
  - `sim_id`, `created_at`, `seed`, `n_samples`, `code_version`, `currency`.
  - `variant`: `masked`, `named`, `both` or `none`. Read from the stored rows, not the checkpoint: each shock of a simulation is stored as `<sim_id>:<shock id>` (`montecarlo.save_simulation`), and an AI shock's own id is the one in `proposal_shocks`, whose proposal sits in a `proposal_sets` row with its `variant`. `none` when no shock traces to a proposal set (manual or guidance shocks only); `both` when shocks trace to sets of both variants (never written by the pipeline or the backtest, but nothing in the schema forbids it).
  - `shocks`: count, and `sources` (the distinct `shocks.source` values: `user`, `computed`, `llm_proposed`).
  - `proposal_sets[]`: each traced set's `set_id`, `variant`, `case_id`, `model`.
  - `pipelines[]`: each pipeline whose checkpoint names this simulation, with `pipeline_id`, `status` and the `variants` it filed it under. Read from the last checkpoint of every `pipeline_runs` row with this `run_id` (done or not: a pipeline that failed after its simulation step still made it).
  - `value_per_share`: the stored `p10`, `p50`, `p90` in the run's currency.
  - `reproduces`: `None` unless `check=True`; then `True` or `False` from `montecarlo.reproduce_simulation` (about a second per 10,000 samples), with its `mismatches`.
  - `notes[]`: codes with parameters, as run warnings are (v0.9.15): `pipeline_variant_differs` (a pipeline filed it under a variant its shocks don't trace to), `shock_not_traced` (an `llm_proposed` shock with no proposal), `sized_elsewhere` (a traced set was sized on another run).
- Ordered masked first, then named, both and none; inside each, pipeline simulations before others, then by the number in the id (`_sim2` before `_sim10`).
- An unknown run id raises `LookupError`-style `SimulationListError`; a run with no simulation returns an empty list.

Command: `python main.py simulations --run-id R [--check] [--json]` (same as `python -m domains.orchestration simulations ...`).

It lives in `domains/orchestration/`, not `domains/analysis/runs.py` as the issue proposed: it reads proposal sets (`domains/llm`) and pipeline checkpoints (`domains/orchestration`), and the analysis domain imports neither. Nothing is stored; no migration.

## Plan

- **Step 0.** This design doc; status in team sync.
- **Step 1.** `domains/orchestration/simulations.py` with the call, its dataclasses and `to_dict`; `graph.state_values(conn, folders, pipeline_id)` (the last checkpoint's values, done or not) used by it. Tests (`tests/orchestration/test_simulations.py`) on Test Corp: a pipeline with both variants gives two simulations, masked first, each with its pipeline and the variant its proposal set has; a manual simulation on the same run is `none` with no pipeline and comes last; `_sim10` sorts after `_sim2`; a pipeline whose checkpoint is edited to file a simulation under the other variant gets `pipeline_variant_differs`; an unknown run raises; a run with none returns `[]`; `check=True` reproduces each and a changed stored output turns `reproduces` false. Exit: tests and ruff pass.
- **Step 2.** The command and its JSON (`to_dict` keys fixed by a test). Exit: CLI tests pass.
- **Step 3.** Real data: on the restored snapshot, every run with a simulation listed; for every finished pipeline, the checkpoint's `sim[variant]` equals the listed simulation of that variant, with no `pipeline_variant_differs` and no `shock_not_traced`; counts of masked, named and none recorded here; `check=True` on a sample. Exit: results recorded below; 0 mismatches.

## Alternatives considered

- **A `variant` column on `simulations` (a migration and a backfill).** A stored fact that duplicates what the shocks already say, and could drift from them; the trace is exact and cheap. If the app ever needs to filter thousands of simulations by variant in SQL, a column can be added then from this same trace.
- **Only the checkpoint.** Misses M8's backtest simulations and manual ones, and a checkpoint can't be queried in SQL.
- **Only the trace.** Would not say which pipeline made a simulation, which the pipeline report and the app's "this run's news" screen need.

## Product impact

Serves brief Q5 (what a news event did to the forecast) on any screen that shows a pipeline run: the app goes from `run_id` to the masked simulation, then to `run_ranges(..., sim_id=S)`. No existing output, name or field changes. New call `domains.orchestration.simulations.run_simulations` and command `python main.py simulations`. Notes are codes with parameters, so the app can say them in Spanish.

## Files to change

`domains/orchestration/simulations.py` (new), `domains/orchestration/graph.py`, `domains/orchestration/__main__.py`, `tests/orchestration/test_simulations.py` (new), `docs/designs/backlog-201-run-simulations.md`, and at merge `docs/versions.md`, `docs/team-sync.md`.
