# Backlog #201 design: list a run's simulations with their variant

Issue #201 (front-end, from the #167 design review, `docs/designs/backlog-167-shocked-range.md`, Product impact). Branch `backlog-201-run-simulations`.

Status: Built, PR open (nov.05.2026).

## Problem

The shocked range (v0.9.16, `run_ranges(conn, run_id, sim_id=S)`) needs a simulation id, but the app holds a run id. The `simulations` table (`shared_kernel/migrations/0008_shocks.sql`) has no column for which news variant a simulation stands for: named (the AI read the company's name), masked (the name hidden; M8's headline variant), or neither (manual or guidance shocks). Today the only way from a run to "its masked simulation" is a pipeline's checkpoint (`graph.final_state(...).sim[variant].sim_id`), which the app should not read (Decision 11 guardrail 4, the engine as a library, as `docs/designs/f2-web-app.md` applies it: the app does no lookups through internals). A run can also have several simulations: one per variant, M8's backtest ones, and any made by hand.

## What the call answers

`domains.orchestration.simulations.run_simulations(conn, run_id, check=False, pipeline_id=None)` returns, for one stored run:

- `run_id`, `ticker`, `as_of`, `checked`, `pipeline_id` (the filter, or null).
- `simulations[]`, one per row of `simulations` with this `run_id`, each with:
  - `sim_id`, `created_at`, `seed`, `n_samples`, `code_version`, `currency`.
  - `variant`: `masked`, `named`, `both` or `none`. Read from the stored rows, not the checkpoint. `montecarlo.save_simulation` stores each shock of a simulation as `<sim_id>:<own id>`; an AI shock's own id is `llm:<proposal_id>` (`domains/llm/review.py`), stored in `proposal_shocks`, whose proposal sits in a `proposal_sets` row with its `variant`. A match also needs the stored shock's driver and first piece of evidence to equal the proposal's, since a shock id is any string a person may type. `none` when no shock traces (manual or guidance shocks, or a simulation with no shock); `both` when shocks trace to sets of both variants (no writer does this: the pipeline and M8 simulate each variant on its own, and reuse keys on a hash that includes the shock ids).
  - `shocks` (count) and `sources` (the distinct `shocks.source` values: `user`, `computed`, `llm_proposed`; an AI shock a reviewer edited is `user` but still traces to its set).
  - `proposal_sets[]`: each traced set's `set_id`, `variant`, `case_id`, `model`, `run_id` (the run it was sized on).
  - `pipelines[]`: each pipeline on this run whose last checkpoint (`graph.state_values`, done or not) names this simulation in its `sim` field, with `pipeline_id`, `status` (`running`, `waiting_review`, `done`, `failed`) and the `variants` it filed it under (a list, in case one simulation is filed under two).
  - `backtests[]`: the M8 eval batches that scored it: `eval_results` rows on this run with the same seed and the matching variant (`llm_masked`, `llm_named`, `with_shocks` for `none`).
  - `value_per_share`: the stored `p10`, `p50`, `p90` (`simulation_outputs`, name `value_per_share`), in `currency`; null if missing.
  - `primary`: true on the first simulation of each variant in the order below: the one to show when a screen asks for "the masked simulation of this run".
  - `reproduces`: null unless `check=True`; then true or false from `montecarlo.reproduce_simulation` (about a second per 10,000 samples: for a button, never a page view). `mismatches` are English lines for the log; the app shows only `reproduces`.
  - `notes[]`: `Coded` items (`code`, `params`, English `text`), from the closed set `domains.analysis.coded.SIMULATION_NOTE_CODES`, next to the run notes' `RUN_NOTE_CODES` (v0.9.15): `pipeline_variant_differs` (`pipeline_id`, `filed`, `traced`), `shock_not_traced` (`shock_id`: an `llm_proposed` shock, or any shock with an `llm:` id, that traces to no proposal), `sized_elsewhere` (`set_id`, `run_id`: a traced set sized on another run).
- Order: masked, named, both, none; inside a variant, one filed by a done pipeline, then one scored by a backtest, then one filed by any other pipeline, then the rest; newest first inside each (`_sim12` before `_sim2`).
- `proposal_sets[]` at run level: every AI proposal set sized on this run with `set_id`, `variant`, `case_id`, `status` (`ok`, `failed`), `no_impact`, `proposals` (review status → count), `sim_ids` (the simulations its shocks went into) and `latest` (the newest set for its case and variant; older ones were redone). This says why a variant has no simulation: the model saw no impact, every proposal was rejected, or the call failed.
- With `pipeline_id`: only the simulations that pipeline filed, and only its proposal sets; a pipeline that is unknown or on another run raises.
- An unknown run raises `SimulationListError` (a `LookupError`); a run with no simulation returns an empty list.

Command: `python main.py simulations --run-id R [--pipeline-id ID] [--check] [--json]` (also `python -m domains.orchestration simulations ...`). Exit 2 for an unknown run, 1 when `--check` finds a mismatch.

It lives in `domains/orchestration/`, not `domains/analysis/runs.py` as the issue proposed: it reads proposal sets (`domains/llm`) and pipeline checkpoints (`domains/orchestration`), and the analysis domain imports neither. Nothing is stored; no migration. The only change to `graph.py` is the new `state_values`.

## Plan

- **Step 0.** This design doc; status in team sync.
- **Step 1.** `domains/orchestration/simulations.py` with the call, its dataclasses and `to_dict`; `graph.state_values(conn, folders, pipeline_id)` (the last checkpoint's values, done or not) used by it. Tests (`tests/orchestration/test_simulations.py`) on Test Corp: a pipeline with both variants gives two simulations, masked first, each with its pipeline and the variant its proposal set has; a manual simulation on the same run is `none` with no pipeline and comes last; `_sim10` sorts after `_sim2`; a pipeline whose checkpoint is edited to file a simulation under the other variant gets `pipeline_variant_differs`; an unknown run raises; a run with none returns `[]`; `check=True` reproduces each and a changed stored output turns `reproduces` false. Exit: tests and ruff pass.
- **Step 2.** The command in `domains/orchestration/__main__.py` and its JSON (`to_dict` keys fixed by a test). Exit: CLI tests pass. (Built in one commit with Step 1.)
- **Step 3.** Real data: on the restored snapshot, every run with a simulation listed; for every finished pipeline, the checkpoint's `sim[variant]` equals the listed simulation of that variant, with no `pipeline_variant_differs` and no `shock_not_traced`; counts of masked, named and none recorded here; `check=True` on a sample. Exit: results recorded below; 0 mismatches.

## Design review (nov.05.2026)

Explainer, analyst and the front-end lead, in parallel; the professor was not asked, since the call computes nothing and chooses no method. Analyst GO, front-end lead GO, explainer twelve gaps. Taken:

- **Analyst.** Real data agrees with the trace (116 simulations on 67 runs; 62 masked, 51 named, 3 none, 0 both; nothing untraced). Should-fix, all taken: a run-level list of proposal sets so a missing variant says why (JNJ_2019-11-15_1: masked set 458 saw no impact); `backtests[]`, a `pipeline_id` filter and done pipelines first, so "the masked simulation" is one defined pick (MSFT_2022-06-02_1 has `_sim2` from its pipeline and `_sim5` from M8's batch); the trace checks the driver and evidence too, and flags any `llm:` id that fails, whatever its source. Not taken: a `several_of_variant` note, since `primary` already marks the pick.
- **Front-end lead.** The principle cited was wrong (now Decision 11 guardrail 4, as F2 applies it); one deterministic pick per variant (`primary`); notes as `Coded` with a closed code set; `mismatches` are for the log only; `check` is for a button, not a page view.
- **Explainer.** The id join, a simulation with no shock, how a checkpoint names a simulation, the status values, `sized_elsewhere`, ids without a number, the error class, where value per share is stored, the files list, and the results section: all now stated above.

## Results on real data (Step 3, nov.05.2026)

On the snapshot `warren-20261104T202442Z` (schema 21):

- 67 runs hold 116 simulations: 62 masked, 51 named, 3 none (guidance shocks in M8's batch), 0 both. Listing all 67 takes 0.6 s.
- Notes: none (no untraced AI shock, no set sized on another run, no pipeline filing under another variant).
- Every one of the 77 simulations filed by the 48 done pipelines that have one is listed under its pipeline with the variant it was filed under, and is that pipeline's `primary`; 0 mismatches. The other 121 done pipelines have no simulation (no impact, or every proposal empty) and are not part of this count.
- Primaries: 77 come from a pipeline, 37 from M8's batches (34 AI, 3 guidance). One run (MSFT_2022-06-02_1) holds two masked simulations; its pipeline's is the primary and M8's is listed with its batch.
- `check=True` on all 116: 116 reproduce to the cent.
- Run-level proposal sets on these runs: 213; 111 went into a simulation, 39 saw no impact, 63 approved shocks that no stored simulation used (earlier sets for the same case and variant, redone later; `latest` is false on them).

## Alternatives considered

- **A `variant` column on `simulations` (a migration and a backfill).** A stored fact that duplicates what the shocks already say, and could drift from them; the trace is exact and cheap. If the app ever needs to filter thousands of simulations by variant in SQL, a column can be added then from this same trace.
- **Only the checkpoint.** Misses M8's backtest simulations and manual ones, and a checkpoint can't be queried in SQL.
- **Only the trace.** Would not say which pipeline made a simulation, which the pipeline report and the app's "this run's news" screen need.

## Product impact

Serves brief Q5 (what a news event did to the forecast) on any screen that shows a pipeline run: the app goes from `run_id` to the masked simulation, then to `run_ranges(..., sim_id=S)`. No existing output, name or field changes. New call `domains.orchestration.simulations.run_simulations` and command `python main.py simulations`. Notes are codes with parameters, so the app can say them in Spanish.

## Files to change

`domains/orchestration/simulations.py` (new), `domains/orchestration/graph.py`, `domains/orchestration/__main__.py`, `tests/orchestration/test_simulations.py` (new), `docs/designs/backlog-201-run-simulations.md`, and at merge `docs/versions.md`, `docs/team-sync.md`.
