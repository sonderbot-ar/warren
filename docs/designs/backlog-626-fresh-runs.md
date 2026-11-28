# Backlog #626 item 1 and #485: fresh runs under today's rules for dates whose newest run was read under older ones

Issues: https://github.com/sonderbot-ar/warren/issues/626 (item 1), https://github.com/sonderbot-ar/warren/issues/485 · Branch `claude/project-thread-juyyyj` (the cloud run's assigned branch) · Version v0.10.60 when merged.

Status: In progress (nov.28.2026).

## Problem

1. **Most stored dates show an answer read under older rules.** A stored run keeps its own assumption rows and reproduces from them to the cent (the invariant), so it is never rebuilt in place. The app shows the newest stored baseline of a company and date (`webapp/answer.find_run` on PR #510). Since v0.10.58 that answer's cost-of-debt cell says `run_read_differently` on 697 of 936 stored runs (#626), including the newest runs of J&J, Microsoft, Walmart and ExxonMobil. The gaps are not only in the cost of debt: Caterpillar's 113 runs before #341 count debt due within a year as zero (#485), and other reading fixes since (the tax rate's one-offs, #400; Coca-Cola's FY2018 fourth quarter; Exxon's successor filings, #573) are missing from runs made before them.
2. **The pipeline reuses a run read under older rules.** `orchestration.nodes._same_inputs` reuses a stored baseline when its ingest, concept map, market downloads and owner choices match today's, but never checks `reading_rules_version`. After a rules change that leaves the map alone (most of v0.10.29 to v0.10.54), `python main.py run` hands back the old reading.

## Plan

**Step 0. This doc.**

**Step 1. The pipeline does not reuse a run read under older rules.**

- `_same_inputs` returns False when the run's `reading_rules_version` is not today's `READING_RULES_VERSION` (null counts as different).
- Test (`tests/orchestration/test_nodes.py`): a stored baseline whose version is set one lower is not reused; the new run has the same value per share on Test Corp (no rule differs there), and is reused on the next call.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Find the stale dates and build a fresh run for each.**

- New `domains/analysis/fresh_runs.py`: `stale_dates(conn, tickers=None)` lists every company and date whose newest stored baseline (the app's pick: no parent, no seed, no LLM-proposed row) was made under other reading rules (or none recorded) or another concept map, with the run, its version and whether the map is today's. `refresh(conn, stale, build=run_baseline)` builds one new baseline per date under today's rules, map and owner choices from the data stored now; a failed build is reported and the rest continue. Nothing stored is changed or deleted.
- Command: `python -m domains.analysis fresh-runs [--ticker T] [--newest] [--dry-run]`. Without flags it builds every stale date of every company; `--dry-run` prints one line per stale date with its run and reason; a failed build prints `FAILED` with the engine's code and the command exits 1. "Newest" is by `created_at`, then `run_id`, as the app orders. "Today's map" is `concept_map_sha256()`, the fingerprint of `domains/fundamentals/concept_map.csv` every run stores. Owner choices are `user_assumptions.csv` as it is today.
- Only the reading is compared, not the downloads: a run under today's rules built from an older filings or price download is not called stale here (the pipeline's reuse check handles that on a pipeline run). A fresh run does read the newest stored ingest, so where filings were added since (Exxon's successor quarters) it reads them too, always cut at its `as_of`.
- Tests (`tests/analysis/test_fresh_runs.py`): a run under today's rules is not stale; older rules, unrecorded rules and another map are, with their reason; only the newest baseline of a date counts; a newer run holding an LLM-proposed row does not hide a stale date; the ticker filter; `refresh` builds a new run under today's version, leaves the old run's outputs equal and reproducing, and clears the date; a fresh run's cost-of-debt cell has no `run_read_differently` where the old run's had; a failed build is reported and the next is built; a fresh run that reads a newer filings download with a filing made after its date reads the same rows as the old run (professor).
- Out of scope: a change to the valuation maths alone (`code_version`) does not make a date stale; `reproduce --all` already catches a maths change, since stored rows must still give their stored outputs.
- Exit: as Step 1.

**Step 3. Real data.** On the restored snapshot: the dry run's count by reason; `fresh-runs` on every stale date; per company the share of fresh runs whose cost-of-debt cell still says `run_read_differently` (expected 0), value per share moves, the largest moves explained from the rows that differ; `reproduce --all` on every run, old and new; a new snapshot.

## Results (Step 3, nov.28.2026)

On the restored snapshot `warren-20261127T002823Z` (936 stored runs, 914 company-dates):

- **914 of 914 dates were stale**: every newest baseline was made through a concept map other than today's; 885 also had no recorded reading rules (made before v0.9.67), 24 version 15 and 5 version 11 (today 16). No date had a newest run under today's rules and map. (Apple's runs read the same values under today's rules; they are stale only by their map's fingerprint.)
- **914 fresh runs built, none failed** (one, Coca-Cola 2026-10-30, as the trial; 913 in the batch; 3 min 24 s offline from stored data).
- **`run_read_differently` on the cost-of-debt cell**: on the old runs Caterpillar 112, J&J 115, Coca-Cola 97, Microsoft 67, P&G 113, Walmart 87, ExxonMobil 91, Apple 0; on the fresh runs 0 for every company.
- **Value per share, fresh against old, same date:** 209 of 913 unchanged (under 0.005%), 702 within 5%, 211 moved more than 5%. Median move per company, with the range: Apple 0.0%, Caterpillar −4.4% (−7.9% to +36.8%), J&J 0.0% (−7.4% to +42.1%), Coca-Cola +2.2% (−1.1% to +53.6%), Microsoft 0.0% (−0.3% to +19.3%), P&G −0.3% (−1.5% to +0.6%), Walmart −0.6% (−1.3% to 0.0%), ExxonMobil 0.0% (−22.2% to +17.9%).
- **What moves them: reading fixes and newer data, mixed.** A fresh run reads today's rules *and* the newest stored filings download (old and fresh runs differ in `ingest_run_id`: Coca-Cola 4 against 184, J&J 6 against 186, Exxon 75 against 188), always cut by filing date at its `as_of`. On past dates the newer download adds nothing filed by then that the old one lacked, so the big moves there are reading fixes; on the newest dates part of the move is new filings.
  - *Reading fixes, past dates.* The tax rate's one-offs (#400): 2017's one-off US tax charge left the average. Coca-Cola's 2019 and early-2020 dates move up about 50% (tax rate 37.8% to 19.5%, and a FY2018 fourth quarter of 5.36B revenue now 7.06B as filed); J&J 2020-03-01 +42% (tax rate 40.2% to 13.9%; its WACC rises slightly, 4.42% to 4.48%, which pulls value down, and 2.6B less debt adds about $1 a share); Caterpillar 2019-05-01 +36% ($90.39 to $123.02: tax rate 43.4% to 21.7%, which outweighs the 5.83B of debt due within a year now counted, #485). Caterpillar's median, −4.4%, is that debt on the later dates.
  - *Newest dates.* Exxon 2026-10-30 $115.35 to $126.41: mostly new data, one more filed quarter from its successor (FY2026 Q2, revenue 116.0B as filed in 0000034088-26-000093 on 2026-08-03; #573), debt 47.7B to 42.4B and cash 8.4B to 10.6B, and a cost of debt of 4.31% instead of 1.41% (interest not on debt taken out and capitalised interest added back, cost-of-debt fixes since v0.10.29). Walmart $31.24 to $31.09; J&J $168.53 to $168.15; Microsoft $203.55 to $203.08; Apple, Caterpillar and P&G unchanged; Coca-Cola $34.73 to $34.76 (2026-10-15).
- **Forecasts:** operating profit moved on 83 fresh runs and revenue on 18 of them: Caterpillar 2019–2020 (15, operating profit only), J&J 2023–2025 (19), Coca-Cola 2019–2021 (28), Exxon 2019–2021 and 2026-10-30 (21). The only newest date among them is Exxon 2026-10-30. So the evaluation's scores would move if they read the fresh runs, and so do the first screen's range bands on those dates (each band is built on the run's own forecast).
- `python -m domains.analysis reproduce --all`: 1,850 of 1,850 runs (936 old, 914 fresh) reproduce to the cent; no stored run's rows changed.

## Decisions in this item

- **The evaluation keeps its links** (#485 asked). `eval_results` and `forecast_origins` keep pointing at the runs they scored. Those scores are the record of what Warren forecast on each date with the code of the time, and the batches reproduce from them (`python -m domains.analysis reproduce --batch`). The stronger reason (professor): today's reading rules were written after seeing those dates' errors (the tax fix was found on these very cases), so scores on fresh runs would not be out of sample (Bailey, Borwein, López de Prado and Zhu 2014; Harvey, Liu and Zhu 2016). A fresh run is today's method on past data, not a real-time vintage in Croushore and Stark's (2001) sense: the data is point-in-time, the method is not. Any later re-score on fresh runs must be labelled "scored with today's rules (hindsight)", never as the forecast record.
- **The LLM's case runs** (`domains/llm/__main__._baseline_run`) take the newest baseline of a case date, so a new proposal from now on is sized on the fresh run; stored proposals stay keyed to the run they read.

## Design review (nov.28.2026)

Explainer, analyst, professor and the front-end lead; each GO with changes, no NO-GO, no blocker; all changes were to this doc plus one test.

- **Taken.** The analyst's corrections to Results: J&J 2020-03-01 is the tax fix (a higher cost of debt pulls value down); Exxon gained one quarter, not two, and its cost of debt moved on interest not on debt and capitalised interest, not leases; fresh runs also read a newer filings download, so moves mix reading fixes and new data; Caterpillar's range and its 2019 tax driver. The professor's out-of-sample reason for keeping the evaluation's links, the vintage distinction, and a test that a fresh run reading a newer download still reads nothing filed after its date. The front-end lead's corrections to Product impact: range bands move where the forecast moved (they are built on the run's own forecast), the default screen's run id changes, and the brief lines that now read wrong. The explainer's gaps: the ordering, the map fingerprint, the default scope, the command's output, and maths-only changes as out of scope.
- **Not taken.** None rejected. The analyst's note that `code_version` varies inside the unrecorded-rules group is recorded as out of scope (Step 2), not a new item: reproduce covers the maths.

## Alternatives considered

- **Rebuild stored runs in place.** Breaks the reproduce invariant and erases the record of what Warren said. Rejected, as in #485.
- **Fresh runs only for each company's newest date** (`--newest`). Covers the app's default date but leaves every past date a student can pick reading the old rules. The full batch takes under four minutes, so it is done for every date; the flag stays for a quick refresh after a future rules change.
- **Let the app pick the newest run under today's rules instead.** Hides the old reading without fixing it and puts a rules check in the app; the fresh run is the answer the engine would give today, and the old one stays one query away.

## Files to change

`domains/orchestration/nodes.py`, new `domains/analysis/fresh_runs.py`, `domains/analysis/__main__.py` (command), new `tests/analysis/test_fresh_runs.py`, `tests/orchestration/test_nodes.py`, `docs/versions.md`, `docs/build-plan.md` (known gaps: Caterpillar's current debt), `docs/team-sync.md`.

## Product impact

Serves brief Q3, Q4, Q5 and Q8 on every stored date: the answer the app shows for a date (its newest baseline, `webapp/answer.find_run` on PR #510, ordered by `created_at` then `run_id`) is now read under today's rules, so its cost-of-debt cell no longer opens with `run_read_differently` and its figures carry every reading fix to date. No output, code, param or text is added, renamed or removed.

- **Run ids.** Fresh runs take the next number for their date (`<TICKER>_<date>_<n+1>`). The default screen now shows a new id: Apple 2026-10-30 is `AAPL_2026-10-30_2`, not the `AAPL_2026-10-30_1` the mockup prints (`docs/product/mockups/f2-screen1-q5.html`); Apple's figures are unchanged. Tests that build their own runs or read the frozen fixture are unaffected.
- **Ranges move where the forecast moved.** The track record reads the evaluation's runs and does not move; each quarter's p10–p90 band is built on the run's own forecast, so it moves on the 83 dates above (the only newest date is Exxon 2026-10-30).
- **Catalogue.** `run_read_differently` stays: an older run picked by id still carries it, and the next rules change makes it fire again until `fresh-runs` is run.
- **Brief text that now reads wrong** (front-end edits, listed in the team-sync entry): `docs/product/brief.md` lines 105 (the version list stops at 15; today 16), 156 ("87 of 115 stored dates", "stored runs never carry either"), 194 ("the 30 stored Coca-Cola runs"), 212 ("697 of 936 … until those runs are rebuilt") and 217 ("every cost-of-debt cell on today's snapshot").
- **Labels** (professor, an idea for the front-end): the value per share is "read under today's rules" while the track record is "scored on the runs of the time"; a student may ask which is Warren's answer.
