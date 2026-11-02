# M8 design: full backtest and Phase 1 review

Status: In progress (nov.02.2026) · Elephant: agent team · Branch `m8-backtest`
Implements Structure Guide Decision 7 (evaluation: error with and without shocks, direction, calibration of the ranges) and Build Plan M8.

## Problem

Phase 1 asks one question: does news make Warren's fundamental forecasts better? Every piece needed to answer it now exists and is stored:

- M3 scores a baseline forecast and a naive one against first-reported actuals, on 26 cases.
- M4 simulates shocks and scores the p50 as `with_shocks` (company guidance, 3 cases).
- M6 stored, for every case, one proposal set per variant (`named`, `masked`), auto-reviewed, sized by code on the case's own baseline run: 36 of 52 sets hold shocks, 16 say "no material impact".
- M7 runs it all as one command, and every run reproduces to the cent (27 of 27, nov.02.2026).

What is missing is the scoring of the LLM's shocks, the metrics that turn errors into an answer (a skill score, a paired test, direction, coverage), and the written review. M8 adds no new forecasting logic, prompt or LLM call. Nothing is tuned on the results: the scales, prompts and case library stay exactly as stored (M6 left calibration to held-out cases, backlog #73).

## What is scored

One batch, all 26 cases, five variants on the **same baseline run per case**:

| Variant | Forecast for a quarter | Band |
|---|---|---|
| `baseline` | the run's revenue and EBIT | none |
| `naive_srw` | the same quarter a year earlier, as known on the case date | none |
| `with_shocks` | p50 under the shocks the company's guidance implies (M4; 3 cases) | p10–p90 |
| `llm_named` | p50 under the auto-approved shocks of the case's `named` set (M6) | p10–p90 |
| `llm_masked` | the same for the `masked` set | p10–p90 |

- **Which run.** The LLM shocks were sized on a stored run (`proposal_sets.run_id`), and M7 refuses to apply shocks to any other run. So the batch scores every variant of a case on that run (`propose.current_set(conn, case_id, variant).run_id`; both variants of every case point at the same run, checked nov.02.2026). The harness gains a `run_id` argument: given, it uses that stored run instead of building a new one, after checking that the run's ticker and as-of date are the case's (`guard_run`) and that the look-ahead guard passes, as for a new run. A case whose two sets sit on different runs fails with that reason.
- **Which set.** `propose.current_set` for the current models, prompts, scales and event choice; the set id goes into each row's batch notes, so a reader can follow a row to its proposals. A case with no current set fails the case (it is never scored as if the LLM said nothing).
- **No shocks, no rows** (the M4 rule). A set that says "no material impact", or whose proposals were all rejected, writes no `llm_*` rows. The summary fills the gap explicitly (see Metrics, "Populations"): in the headline a case without rows takes the baseline forecast, because "no shock" is the LLM's answer and the forecast a user would have got.
- **Seeds.** Every simulation of a case uses `case_seed(case_id)`, the M4 seed, N = 10,000, so a batch draws the same samples every time it runs. This is **not** common random numbers across variants: `montecarlo.py` gives z column i to the i-th shock in stored order, and the named and masked lists differ in length or order in 6 cases (PG_2019-07-30 named holds [revenue_growth], masked [operating_margin, revenue_growth]; analyst review). The gap between variants therefore includes sampling noise in the band; the p50 of a one-shock band is the shock's base whatever its column, and with N = 10,000 the noise in a p50 is small next to the errors scored. Keying z by driver would change every stored simulation, so it is not done in M8. A stored simulation with the same run, seed, N and `shocks_sha256` is reused, as M7 does.
- **Point-in-time.** The shocks rest on events that the M6 case window already limits to the 7 New York days ending on the case date. The batch checks it again, independently, on **every** event a scored shock cites: `shocks → proposal_shocks → shock_proposals.evidence_json` (a proposal cites 1–6 events; `Shock.event_id` holds only the first, `review.py:27`). Each cited event's `last_seen`, converted to New York time, must fall on or before the case date, else the case fails (`guard_event_dates`). Times are compared in New York, never as UTC dates: AAPL_2020-02-17 has an event last seen at `2020-02-18T00:45Z`, which is 19:45 on the case date in New York. A test pins that near-midnight case both ways. Guidance shocks keep `guard_source_dates`.
- **Storage.** Migration `0016_eval_variants.sql` widens the `variant` check of `eval_results` to the five names (SQLite rebuilds the table; rows copied unchanged, a migration test on a v15 database with stored rows). No new table: p10/p50/p90/seed already exist (0007). The batch's `notes` record the guidance file's SHA-256 and the set ids per case and variant, as JSON.

## Metrics

All computed in `domains/evaluation/backtest.py`, pure functions on stored rows, with tests on hand-made rows. A case's quarters are M3's: h1 is the fiscal quarter after the last one reported on the case date, up to the case's `horizon_quarters` (m3-evaluation-harness.md, "What is measured"). The unit of evidence for tests is the **case**, not the quarter: a case's 1–4 quarters share one forecast run and one set of shocks, so they are not independent (backlog #24).

**Populations** (fixed here, before any result is seen; explainer and professor review). Each variant is judged on its own; named and masked never borrow each other's rows.

- **All cases (the headline).** Every scored case. For a case or item with no rows in the variant, the variant's forecast is the baseline's. This is the comparison "what a user of Warren would have got" (an intention-to-treat reading: the LLM's choice not to act is part of the method).
- **Moved items** (secondary). For each case and item, the item is *moved* in a variant when any scored quarter's p50 differs from the baseline by more than half a cent. Risk-premium and capex shocks do not move revenue or EBIT, so a case can hold shocks and move neither (JNJ_2021-11-12 masked; analyst review). This view shows where the shocks actually changed the forecast; it is selected by the LLM's own choice, so it is never the headline.
- **Without scope changes** (secondary). The headline again without the cases whose `scope_change` names a deal closing inside the horizon (MSFT_2023-10-13, KO_2021-11-01, XOM_2023-10-11 among the events). There the baseline cannot see acquired revenue, so a shock that adds it wins almost by construction (analyst review).

Every table states its n (cases and quarters).

1. **Error** as M3: revenue in % of the actual (APE), EBIT in margin points. Medians, and the interquartile range.
2. **Skill score** against a reference variant, pooled over quarters: on matched rows (same case, item, quarter, both `ok`), SS = 1 − mean error(variant) / mean error(reference). Murphy (1988) defines the skill score on mean squared error; Warren applies the same form to its own errors (APE for revenue, margin points for EBIT), as in Hyndman & Athanasopoulos, *Forecasting: Principles and Practice*, 3rd ed., §5.8–5.9 (scaled errors and skill scores). Above 0 means better than the reference. Reported per item (never pooled across items), against `baseline` (the Phase 1 question) and against `naive_srw`. A median version, 1 − median / median over the same quarter rows, is shown next to it, because a few cases dominate means on 26 cases.
3. **Paired test, per case** (the "beat" test M3 left to M8). For each case and item, d = mean error(variant) − mean error(baseline) over the case's scored quarters. The **exact two-sided sign test** on the cases with d ≠ 0 (binomial, p = ½): ties (d exactly 0, as in every unmoved case) are counted and shown, never counted as wins or losses. Next to it, a **case bootstrap** 90% interval for the mean of d: cases resampled with replacement, 10,000 draws, a fixed seed (`20261102`), percentile interval. With 26 or fewer clusters, percentile intervals tend to cover less than they claim (Efron & Tibshirani 1993, *An Introduction to the Bootstrap*, ch. 14); the limitations say so. Diebold–Mariano (1995) is not used: it rests on a long series of loss differences and on an estimate of their autocorrelation, and here there are at most 4 correlated quarters per case and 26 cases. With 26 cases the test has little power: a "no difference" result is reported as "not shown", never as "no effect". `with_shocks` has 3 cases, so its smallest possible two-sided p is 0.25; the report says it cannot reach significance. d is also shown **by horizon** (h1…h4, mean over cases), because a shock that starts in quarter 2 leaves h1 unshocked (AAPL_2020-02-17; analyst review).
4. **Direction.** Each quarter's forecast and actual are classed up, flat or down by `harness.direction`, the same rule for both items: a change within ±0.5% of the prior-year value is flat (relative change in revenue or EBIT, not margin points). The actual is compared with the comparative from the filing that first reports it; the forecast with the prior year as known on the case date (M3). A hit is the same class, so a flat actual is hit only by a flat forecast. Quarters whose actual direction is unknown are left out, and counted. Beside the hit rate: the base rate (share of actual quarters that rose: the score of "always up") and `naive_srw`'s hit rate. For the shocked variants, the direction of the p50.
5. **Coverage of the p10–p90 band:** the share of actuals with p10 ≤ actual ≤ p90 (ends count as inside), on `ok` rows of the shocked variants, by item, with the count and a 95% Wilson interval for the share. Decision 7 asks for about 80%. **This band is shock-size uncertainty only** (M4, "The baseline is not sampled"): a quarter that no shock touches has p10 = p50 = p90, so coverage is expected to fall far short. The report states this before the number and shows coverage on the quarters a shock moved (p90 > p10) apart from the rest. A calibrated band needs the baseline's own uncertainty, which is new modelling, not scoring; it is a Phase 2 item in the review, not built in M8 (see Alternatives).
6. **Interval score** at α = 0.2, in the "lower is better" form (Gneiting & Raftery 2007, §6.2, eq. 43, which writes it with the opposite sign): IS = (p90 − p10) + (2/α)·(p10 − y)·[y < p10] + (2/α)·(y − p90)·[y > p90], divided by the actual revenue of the quarter for both items, so it is in the same units as the error (% of revenue). A point forecast is an interval of width 0, so the baseline's IS is 10 × its absolute error over revenue. Both are computed on the same matched quarters (the moved quarters of the shocked variant), so the two numbers compare like for like.
7. **By event type.** The headline tables are also shown by the case's hand-assigned `event_type` (cases.csv: guidance, m_and_a, restructuring, litigation, regulation, supply_chain, macro, control; each case in exactly one) and by driver of the shocks applied (a case with shocks on two drivers appears in both driver groups, so those groups overlap and are not summed). With 1–5 cases per type these are **descriptive only**, said in the table's caption. Controls are where shocks should do nothing: any shock on a control and its effect on error is shown on its own line ("noise").
8. **Named against masked.** Both are reported side by side, with the M6 caveat repeated next to them: the gap mixes the model's memory of what came next with the distraction effect of the name (Glasserman & Lin 2023), so it is not a measure of look-ahead on its own. Also counted: cases where the two variants move an item in **opposite directions** (PG_2019-07-30 named raises revenue, masked cuts it; analyst review), a sign of how unstable the proposals are. The post-cutoff count is M6's: each case is pre- or post-cutoff by its date against the training cutoffs recorded in `shared_kernel/config.py` (`training_cutoff`, from Anthropic's models overview, M6 Step 8); every case is before both, so the count is zero.

The headline the review answers from is fixed now: per item, the skill score against the baseline and the sign test, on **all cases**, for `llm_masked` (the variant with the smaller leak), with `llm_named` beside it.

## Reproducibility (exit criterion)

`python -m domains.evaluation reproduce --batch BATCH` re-scores every row of a stored batch from stored data only: the run's outputs, the simulation's percentiles re-run from its stored shocks and seed (`montecarlo.reproduce_simulation`), and the actuals as first reported as of the batch's stored `actuals_as_of` (in its notes; backlog #21 asks for a column, the notes field holds it until then). It checks each row's forecast, p10/p50/p90 and error to the cent (forecasts and bands in currency units to 0.005; errors to 1e-9), that the set ids in the notes are still each case's current sets and the guidance file's SHA-256 is unchanged, and prints the batch's code version against today's. Tests: a stored batch reproduces; an edited stored shock, or an edited percentile, fails it.

## Commands and report

- `python -m domains.evaluation backtest [--guidance PATH] [--case ID ...]`: runs the batch above (all five variants), writes `data/reports/eval/<batch_id>.md` (M3's report, unchanged sections) and `data/reports/eval/<batch_id>_backtest.md` (the M8 tables). Exits 1 only if no case could be scored. Cases that fail are listed with their reason.
- `python -m domains.evaluation reproduce --batch BATCH`.
- The backtest report: the headline (skill, sign test, bootstrap interval, per item and variant); direction; coverage and interval score with the shock-only caveat first; by event type (descriptive); named against masked; the per-case table of d with the shocks' drivers and classes; a glossary; the limitations (hindsight-chosen events, 26 cases, the model's memory, shock-only bands, scales not calibrated).

## The Phase 1 review

`docs/phase1-review.md`, written from the stored batch after it runs: what worked, what failed, which event types help and which add noise, the cost, and what Phase 2 should tackle. Every claim cites a table of the backtest report or a test. A negative result is reported as such.

Anything learned that touches a decision is written in the review as a proposal. Decision-log updates in M8 are status notes on Decisions 6 and 7 (what M8 measured, with the date); changing or adding a decision goes to the owner as a decision card (CLAUDE.md), never in this PR.

## Steps

- **Step 0.** This design doc; M8 "In progress" in the build plan.
- **Step 1.** Migration 0016 (five variants), `guard_run`, `guard_event_dates`, and the harness generalised from one band to a band per shocked variant (`evaluate_case(..., run_id=..., shock_sets={variant: shocks})`), keeping `guides` as it is. Tests on Test Corp: a stored run is used and refused when its ticker or date differs; a revenue-cut set gives `llm_named` rows whose p50 is below the baseline and whose p10 ≤ p50 ≤ p90; a no-impact set writes no rows; a cited event first seen after the case date fails the case; named and masked of one case use the same seed; the migration keeps stored rows on a v15 database; every existing harness test passes unchanged.
- **Step 2.** `backtest.py` metrics: skill score, per-case d, the exact sign test, the case bootstrap, direction with base rate, coverage (all, and moved quarters only), the interval score, groupings by type and driver, the all-cases view (no rows → baseline). Tests on hand-made rows with hand-computed answers: skill 0 when equal, > 0 when better; sign test p for 5 of 5 = 0.0625 and ties excluded; bootstrap interval reproduces with its seed and collapses to a point when every d is equal; coverage counts the ends as inside; the interval score of a hit is its width, of a miss width + 10 × the miss.
- **Step 3.** `backtest` and `reproduce` commands, the backtest report, and `domains/evaluation/backtest_batch.py` that wires cases → current sets → the harness. Tests: the CLI end to end on Test Corp with a fake stored proposal set; reproduce passes on the stored batch and fails on an edited shock and an edited percentile.
- **Step 4.** The real batch. Data: `python -m shared_kernel.snapshot restore --dir /mnt/project-files/warren-data/` (done nov.02.2026: `warren-20261101T204102Z`, schema 15), then `python -m domains.analysis reproduce --all` (27 of 27 to the cent, nov.02.2026). No download and no LLM call is needed: all runs, events and sets are stored. The batch is the first stored one (`eval_batches` is empty after the M6 rebuild), then `reproduce --batch` on it, the results in this doc and the build plan, `docs/phase1-review.md`, status notes on Decisions 6 and 7. A snapshot is saved after the batch. M8 Done on merge.

Steps 1–4 go in one PR (one PR per item, CLAUDE.md): Steps 1–3 change no stored number and no existing variant's rows, and Step 4 needs no network. The M3 report written by `backtest` is the existing `report.py` output, unchanged; the new variants appear only in the backtest report.

## Exit criterion (Build Plan)

The review exists, and the results reproduce from stored seeds and code version (`reproduce --batch` passes on the real batch). A negative result is a valid outcome.

## Alternatives considered

- **Score the LLM shocks on a fresh baseline run.** Rejected: the shocks were sized on a stored run (σ from its history, bounds from its path), and M7 forbids applying them to another; a fresh run would also hide a drift between runs that reproduce checks separately.
- **Copy the baseline into `llm_*` rows when there are no shocks.** Rejected (M4 rule: no copy under another name). The all-cases view gets the same effect in the summary, explicitly.
- **Diebold–Mariano or a t-test on pooled quarters.** Rejected: too few, correlated losses; the per-case sign test and a case bootstrap make no distribution assumption and respect the clustering.
- **Add baseline uncertainty to the bands now** (sample the drivers, or widen by the baseline's past errors). Rejected for M8: it is a new forecasting method, and fitting its width on these 26 cases would tune it on the test set. Phase 2 item: a band from the baseline's own errors on dates before each case (point-in-time), tested on held-out dates.
- **Calibrate the size multiples on the results.** Rejected for the same reason (backlog #73, held-out cases).
- **Weight cases or drop outliers.** Rejected: every case counts once; removing a case is the owner's decision (M3).

## Files

New: `shared_kernel/migrations/0016_eval_variants.sql`, `domains/evaluation/{backtest,backtest_batch,backtest_report}.py`, `tests/evaluation/test_{backtest,backtest_batch}.py`, `tests/shared_kernel/test_migration_0016.py`, `docs/phase1-review.md`.
Changed: `domains/evaluation/{harness,__main__}.py`, `docs/{build-plan,structure-guide,versions}.md`.

## Review log

- **Explainer** (6 gaps called blockers, all answered): which population each statistic uses (Metrics, Populations; the headline is all cases); the skill score's unit (pooled quarter rows per item); named and masked judged apart; the direction rule for EBIT and flat quarters (Metrics 4); where the post-cutoff count comes from (Metrics 8); the restore and reproduce checks before Step 4. Gaps answered: groups overlap by driver, not by type; quarters as M3; reproduce rechecks set ids and the guidance hash; one PR; the M3 report unchanged.
- **Analyst** (2 blockers, both accepted; GO once fixed): the event guard read only each shock's first event, and must compare in New York time (now every cited event, in New York, with a near-midnight test); common random numbers was claimed but z is keyed by shock position and the lists differ in 6 cases (claim withdrawn, explained under Seeds). Ideas taken: "moved" per item; with and without scope changes; named-vs-masked direction flips; d by horizon; `with_shocks` can't be significant; Step 4 makes the first stored batch.
- **Professor** (GO, no blockers): ideas taken: the headline population fixed before results; citations (FPP3 §5.8–5.9, Murphy on MSE, G&R §6.2 sign); interval score on matched quarters with the width-0 reading; a Wilson interval on coverage; the bootstrap's small-cluster caveat; naive's direction hit rate. To backlog: Wilcoxon signed-rank and Pesaran–Timmermann as sensitivity checks, a BCa interval, Christoffersen's coverage test, a worked example for students.

## Where the work stopped

- nov.02.2026: Step 0 written; design review done (explainer, analyst, professor), all blockers answered in the doc. Step 1 next.
