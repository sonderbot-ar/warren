# M10 design: more test dates, chosen by rule, some after the models' cutoff

Status: In progress (nov.02.2026) · Elephant: agent team · Branch `m10-more-dates`
Implements the second item of the Phase 2 direction (Build Plan §4b, owner decision nov.02.2026) and the post-cutoff test that Build Plan §7 lists against "LLM knows the outcome of historical events".

## Problem

The Phase 1 answer to "does news make Warren's forecasts better?" is **not shown** (`docs/phase1-review.md`, "The answer"): on 26 cases the AI's shocks cut error by 2.1% (revenue) and 1.5% (EBIT, masked), with sign tests at p 0.79 and 0.82. Three things stop a firmer answer:

1. **Too few cases.** Only 14 (revenue) and 18 (EBIT) of 26 masked cases moved at all; the sign test runs on those. A 2–5% gain can't be told from zero on that count.
2. **The cases were picked in hindsight** as notable events (`docs/designs/m3-evaluation-harness.md`, Case library). Notable events are where news should help most, so the 26 cases can flatter the method, and the controls are only 8.
3. **Every case is before the models' training cutoff** (June 2026 for both models, `shared_kernel/config.py:78-81`), so the named variant's small edge over masked could be the model remembering what happened next (`docs/phase1-review.md`, "Named and masked disagree").

M10 adds test dates chosen by a calendar rule fixed before any result is seen, for every company in the universe, including dates whose whole news week is after the cutoff. Each new date runs through the one-command pipeline (M7), is scored as in M8 (same metrics, same headline) and gets M9's range.

What M10 does not do: no new forecasting logic, prompt, scale or shock rule; nothing is tuned on the results (M6 and M8 rule; calibration waits for held-out cases, backlog #73). Merger sizing (#102), commodity baselines and the Exxon successor link (#126) stay where they are.

## The date rule (fixed here, before any result)

A **grid case** is one company of the universe (`domains/fundamentals/universe.csv`, never a hard-coded list) on one **grid date**:

- **Pre-cutoff grid:** the 1st of January, April, July and October, from 2019-04-01 to 2026-04-01 (29 dates). Quarter starts are a fixed calendar, so where a date falls relative to filings and news is not chosen; every company is on every date, so one GDELT week serves all of them.
- **Post-cutoff grid:** the 1st and the 15th of every month whose 7-day news window starts after the last cutoff month has ended: 2026-07-15, 2026-08-01, 2026-08-15, 2026-09-01, 2026-09-15, 2026-10-01, 2026-10-15 (7 dates). Twice as dense as monthly because these dates are the scarce resource; fixed now, not after a look. A date is **post-cutoff** when its window's first New York day (`as_of − 6 days`) is after the end of the latest model cutoff month among `NODE_MODELS`. "Jun 2026" is month-only, so data through June 30 is assumed; 2026-07-01 (window Jun 25 – Jul 1) is therefore not post-cutoff and is not on either grid. M8's count compared the case date with the first of the cutoff month (`backtest_report.py:322`), which is too loose; M10's reports use this rule.
- The last grid date is 2026-10-15 because a case needs at least one forecast quarter with a reported actual. Later dates are added by a future run with the same rule (the generator takes an end date), never by hand.

**Who is left out, by rule:** a company on a date on or after its `history_ends` (Exxon from 2026-08-03, universe note) is not a grid case; it is counted in the report. A case that fails in the pipeline or the harness (engine error, coverage guard, no prior-year row) is stored with its reason and counted, never dropped silently. A grid date that coincides with a hand-picked case of the same company would share its case id; the generator refuses that (none does today).

36 dates × 8 companies = 288 slots; Exxon's 5 post-cutoff dates from 2026-08-15 are out by rule, so **283 grid cases** (232 pre-cutoff, 51 post-cutoff). Exxon's two post-cutoff cases before the cut (2026-07-15, 2026-08-01) may still fail the coverage guard (#126); they are counted if so.

**Horizon.** 4 quarters, as M3 and M9; only quarters with an actual reported by the batch's `actuals_as_of` are scored. Post-cutoff cases mostly score h1 only (a 2026-10-15 case's h1 is the September quarter, reported late October; Walmart's October quarter reports in mid-November). The report shows how many quarters each group scores.

## Storage

The grid lives in a checked-in file, `domains/evaluation/grid_cases.csv`, with the same columns as `cases.csv`: `event_type` = `grid`, `description` "Grid date: no event chosen", `selected_because` "grid rule: quarter start" or "grid rule: post-cutoff 1st/15th", no source URL. It is **written by the generator** (`python -m domains.evaluation grid --write`) and checked by the loader, which regenerates it from the rule and the universe and fails if the file differs, so a hand edit can't sneak a date in or out. Each batch stores the file's SHA-256 as today. The grid rows go into `eval_cases` like any case, so the pipeline treats them as eval cases (both variants, auto review for dates over 7 days old, M7). No migration: `eval_cases.event_type` has no check constraint (to be confirmed in Step 1; if it has one, migration 0018 widens it, with a test on a v17 database).

## Running the cases

`python -m domains.evaluation run-grid [--from D] [--to D] [--ticker T ...] [--dry-run] [--max-tokens-total N]` runs the M7 pipeline (`main.py run --ticker T --as-of D --review auto --variant both`) for every grid case not yet done, date by date, so each GDELT week is downloaded once (`fetch_news` reads a window only when it isn't fully read) and then serves all eight companies. It reuses everything the pipeline reuses (stored filings, prices, events, answers); a failed or paused case resumes. The seed is `harness.case_seed(case_id)`, so the simulations are the ones the backtest draws. `--dry-run` counts the LLM calls and input tokens before any is made; `--max-tokens-total` is one budget across the whole command (the pipeline's own budget, summed), and the command stops cleanly when it would be passed, leaving the remaining cases for the next run.

**Order:** post-cutoff dates first (they are the new evidence), then the pre-cutoff grid from the newest date back, so a budget stop leaves a usable, dated subset rather than a random one.

**Cost.** Free except the AI calls. The GDELT week for one date is 672 files, about 5.5 minutes (M7 Step 6), so 36 weeks ≈ 3.3 hours of download. AI: the M7 Walmart date cost about 4 cents for one variant (15 events); two variants ≈ 8 cents, so 283 cases ≈ $15–25, less where a week has few events. This is above the M6 run ($5.81), so it goes to the owner first (CLAUDE.md: anything that costs money). Everything before the AI step (filings, prices, news, events, baselines) is free and runs while the card waits.

## Scoring

One backtest batch over the grid (`backtest --cases grid`), on the same stored run per case that the shocks were sized on (M8, "Which run"), with the M8 variants (`baseline`, `naive_srw`, `llm_named`, `llm_masked`; no guidance file for grid dates). Every M8 metric, unchanged, from `domains/evaluation/backtest.py`. Then M9's ranges on the batch (`ranges test --batch`), pooled, with the build's errors as known on each case's date.

**The headline (fixed now)**, per item: on **all grid cases**, the `llm_masked` skill score against the baseline and the per-case exact sign test with its case-bootstrap 90% interval, `llm_named` beside it, exactly M8's headline. The 26 hand-picked cases are reported beside, never pooled into the headline (they were chosen in hindsight).

**The memory test** (secondary, fixed now). For each case and item, g = d(named) − d(masked), where d is M8's per-case error difference against the baseline (below 0: named helped more). Reported: mean g with a case-bootstrap 90% interval, pre-cutoff and post-cutoff, and their difference. If the named edge comes from memory, g should be below zero before the cutoff and near zero after. The name's distraction effect (Glasserman & Lin 2023) is present on both sides, so the change in g across the cutoff is the cleaner signal than g alone. With about 50 post-cutoff cases scoring mostly one quarter, this test has little power; "no change shown" is reported as "not shown", never as "no memory".

**Also reported:** the headline by pre- and post-cutoff; how many grid cases had no events, no material impact, or shocks (the share of quiet dates is itself a result: the grid's weeks are ordinary weeks); the M9 range coverage on grid cases (baseline and combined), beside the rolling test; the cases left out or failed, with reasons; the scored-quarter counts per group.

**Why the headline does not change from M8's.** Holding the metrics, the population rule and the variant fixed is what makes the grid a test of M8's finding rather than a new search. More cases is the only change.

## Reproducibility

`reproduce --batch` (M8) and `ranges reproduce` (M9) on the new batch and build, unchanged. Every grid run reproduces with `analysis reproduce --all`. The grid file's SHA-256 and the regenerate check pin the case list.

## Steps

- **Step 0.** This design doc; M10 "In progress" in the build plan.
- **Step 1.** `domains/evaluation/grid.py`: `grid_dates(end)`, `is_post_cutoff(d)`, `grid_cases(universe, end)`, `write_grid`, and the loader (`load_cases(GRID_PATH)` with `grid` admitted only from the grid file, and the regenerate check). `grid_cases.csv` generated and checked in. Tests: the date list is the rule's (first, last, count, 2026-07-01 absent); `is_post_cutoff` on Jun 30 / Jul 1 / Jul 7 / Jul 8 windows; Exxon left out from 2026-08-03; a hand-edited file fails the loader; a collision with `cases.csv` fails; a company added to a test universe appears on every date with no code change.
- **Step 2.** `run-grid`: the date-by-date driver over the M7 graph, the shared token budget, the order, resume, `--dry-run`. Tests on Test Corp with fake GDELT and a fake client: one window download serves two companies; a budget stop leaves later cases undone and resumes; a failed case is stored with its reason and the next case runs; post-cutoff dates run first.
- **Step 3.** `backtest --cases grid` (the case file as an argument; no change for the default), the report's grid sections: pre/post split, the memory test, quiet-date counts, left-out cases; the cutoff rule shared with the M8 report. Tests: hand-made rows give the hand-computed g and its bootstrap; the post-cutoff rule is the one in the report; the default `backtest` output is unchanged.
- **Step 4.** Data (free): restore the snapshot; refresh filings for all companies (the Q3 2026 10-Qs filed in late October); prices and rates; GDELT for the 36 weeks; events. `analysis reproduce --all` before and after. Snapshot saved.
- **Step 5.** The AI run, after the owner's answer on the budget: `run-grid --dry-run`, then `run-grid` within the approved cap. Then the batch, `reproduce --batch`, `ranges test --batch` and `ranges reproduce`; results written below; snapshot saved. M10 Done on merge.

Steps 1–3 change no stored number. **Exit criterion:** the grid batch is stored and reproduces; the report states the headline on all grid cases, the pre/post split and the memory test, with counts of cases scored, failed and left out.

## Alternatives considered

- **Event dates from SEC 8-K filings** (every 8-K with items 1.01, 2.01, 2.05, 7.01 or 8.01, from the EDGAR submissions file). Hindsight-free and closer to "news days", but each date needs its own GDELT week (no sharing across companies: about 8× the download) and the filing item mix shifts with each company's habits. A good second grid later; the calendar grid is the cleaner first test.
- **Earnings-week dates** (the 1st of February, May, August, November, when most of the eight report). News-rich, but the week's headlines report the quarter the baseline has not filed yet, which is the "start rule for quarters that ended before the news" problem M8 sent to the backlog (#115); quarter starts sit between earnings seasons for most of the eight.
- **All 728 M9 origins.** The baselines exist, but 91 news weeks and about $60 of AI calls, for overlapping monthly dates whose errors are strongly correlated; quarterly dates give most of the independent information for a third of the cost.
- **Random dates.** No better than a fixed calendar at avoiding hindsight, and they break the one-week-for-all-companies sharing.
- **Pool the grid with the 26 cases.** Rejected for the headline: the hand-picked cases would weight it towards notable events; they are shown beside.
- **Wait for more post-cutoff quarters.** The post-cutoff set grows every month; the generator's end date moves forward in a later run, under the same rule.

## Files to change

New: `domains/evaluation/grid.py`, `domains/evaluation/grid_cases.csv`, `domains/evaluation/grid_run.py`, `tests/evaluation/test_grid.py`, `tests/evaluation/test_grid_run.py`. Changed: `domains/evaluation/{cases,__main__,backtest_report}.py`, `docs/build-plan.md`, at merge `docs/versions.md` and a status note on Decision 7 in `docs/structure-guide.md` (no decision changes).

## Where the work stopped

- nov.02.2026: Step 0 written; design review next.
