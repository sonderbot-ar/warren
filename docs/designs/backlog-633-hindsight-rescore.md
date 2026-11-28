# Backlog #633: a hindsight re-score of the monthly forecasts on the fresh runs

Issue: https://github.com/sonderbot-ar/warren/issues/633 · Branch `claude/project-thread-8md91m` (the cloud run's assigned branch) · Version v0.10.61 when merged.

Status: In progress (nov.28.2026).

## Problem

v0.10.60 built a fresh baseline under today's reading rules for every stored date (914). The evaluation keeps scoring the runs of the time, which is right: that is the record of what Warren said, and today's rules were written after seeing those dates' errors (the tax fix, #400, was found on these cases), so a score on fresh runs is not out of sample (Bailey, Borwein, López de Prado and Zhu 2014). But nobody can say today how much the reading fixes since M9 moved the forecast error. The fresh runs move operating profit on 83 dates and revenue on 18, so the answer is not zero.

1. **No side-by-side score.** There is no way to score a fresh run with the same rules and the same actuals as the run of the time, and see the two errors together.
2. **Maths-only changes** (#633 item 2): `fresh_runs.stale_dates` compares the reading rules and the concept map only. Should a change to the valuation maths alone also make a date stale?

## Plan

**Step 0. This doc.**

**Step 1. The re-score, read-only.**

- New `domains/evaluation/rescore.py`. `hindsight_rescore(conn, tickers=None, actuals_as_of=None)` takes every M9 forecast origin stored `ok` (`forecast_origins`), finds that company and date's newest baseline under today's reading rules and concept map (the fresh run; the same pick as `fresh_runs._NEWEST`, filtered to today's version and map), and scores **both** the origin's run of the time and the fresh run with the M9 code itself and the same actuals: `harness.evaluate_case(..., run_id=...)` on `ranges.origin_case`, then `ranges.error_rows`, as `ranges.reproduce_build` does. Scoring both live keeps the actuals' reading code the same on both sides (analyst: `facts.py` is a reading-rules module, so stored misses read their actuals under older code). How many stored misses differ from the run of the time scored today is counted apart (`stored_drift`) and does not enter the comparison. Actuals are read as first reported, as known on the last day that has ended in New York (`--actuals-as-of` to pin it); a first-reported figure does not change with a later actuals date, and the equal-actual rule below drops any quarter where it did.
- A quarter is **compared** only when both rows are `ok`, for the same **period** and item (not the same horizon: a fresh run that reads one more filed quarter forecasts the same period at a shorter horizon; the pair keeps the old horizon), with the same actual and actual revenue to the cent. Anything else is counted apart with its reason: an origin that failed when built (and whether it has a fresh run), no fresh run for the date, the fresh run is the origin's own run, a run fails to score (its engine message), a status differs, the actual differs. A fresh run's extra quarters are not compared.
- Output, per company and item (revenue, operating profit), pooled, and pooled per horizon (h1 to h4): compared rows and **distinct quarters** (one quarter is forecast from up to twelve monthly origins, so rows are not independent), rows whose error moved (more than 1e-9) split into better and worse (absolute error down or up), mean absolute error of each run and the difference, the difference on moved rows only, and the median of each. Revenue errors are 100 × |ln(actual / forecast)|, read as %; operating profit in margin points of actual revenue, as M9 stores them. The two largest moves of each company, by absolute change, ties by origin, horizon and item.
- **No significance test** (professor): today's rules were chosen after seeing these errors, so a Diebold-Mariano test would not hold its size (Diebold 2015; White 2000), and overlapping quarters make the rows strongly dependent. The report says so and gives descriptive numbers only.
- **Nothing is stored.** No table, no row, no batch. The result is a pure function of stored runs and stored filings, so a second call gives the same numbers (tested); there is no stored result to reproduce or to be mistaken for the record.
- Command: `python -m domains.evaluation rescore [--ticker T] [--actuals-as-of D]` writes `data/reports/eval/rescore_hindsight.md` and prints the pooled lines. The report's title and every table say "Scored with today's rules (hindsight)" and the first paragraph says why it is not the forecast record.
- Tests (`tests/evaluation/test_rescore.py`, on Test Corp, `tests/analysis/conftest.py`): a fresh run whose forecast equals the old one compares with zero change and no drift; a fresh run with one quarter's revenue 10% higher moves that error by −ln(1.1) and nothing else; an origin with no fresh run, and one whose stored run is already under today's rules, are counted apart; a differing actual is not compared; quarters pair by period, keeping the old horizon; nothing is written (row counts of every table equal before and after) and two calls agree; the report says the label in its title and every results table, and says it is not the record and runs no test; the command writes the report.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot: the command on every origin; per company and item the old and fresh mean absolute error, the better and worse counts; the largest moves explained from the assumption rows that differ between the two runs; `reproduce --all` and `ranges reproduce` still OK (nothing stored moves). Exit: the command finishes with no failed origin, or each failure explained; the reproduce checks pass.

## Decisions in this item

- **Item 2: a maths change is already a reading-rules change, so nothing new is needed.** (Rewritten after the analyst's blocker: the first draft said a maths-only change does not make a date stale, but `financial_math.py`, `dcf.py` and the rest of what `math_engine.py` imports are in `reading_rules.rules_modules()`, `domains/analysis/reading_rules.py:3-13`.) A code change there changes `rules_fingerprint()`, and the test forces a row in `reading_rules.md`: the next version, which makes every date stale for `fresh-runs`, or the same version with a reason when no value can move. A change that moves a stored run's outputs from its stored rows also fails `reproduce --all`, and relaxing that invariant is an owner decision. `fresh_runs.py`'s docstring now says this.
- **Only the M9 origins.** They are the one set scored on a fixed monthly rule (728 origins) with every quarter's miss stored. The M8 and M10 batches score shocked variants sized on the runs of the time; re-scoring their baselines alone would compare a baseline that the shocks were never sized on. Left for later if asked.

## Design review (nov.28.2026)

Explainer, analyst and professor; GO with changes from each; one blocker (analyst), fixed. The front-end lead was not asked: *Product impact* is "none" for the screens.

- **Taken.** Analyst: item 2's premise was wrong (blocker; rewritten above); score both runs live with the same actuals and count stored drift apart; count failed origins; pair by period and report per horizon; distinct quarters and better/worse counts; largest moves per company, so J&J's and Coca-Cola's do not crowd out the rest. Professor: no significance test, and the report says why; distinct quarters; the change on moved rows only and better/worse counts; say once what a revenue error is. Explainer: the fresh-run pick named, the default actuals date, the conversion to %, the ranking rule, Step 2's exit, the test company.
- **Not taken.** The professor's optional spread from `ranges_report.cluster_bootstrap`: with the rules chosen on these errors a spread invites the reading of a test; left out. The worked example at the top of the report: the report's largest-moves table gives each move; the desk lesson walks through one. The explainer's branch-name note: cloud runs push to the assigned branch, as v0.10.60 did.

## Alternatives considered

- **Store the re-score as a new batch kind.** The issue suggested it. Rejected for now: a stored hindsight score sits in the same tables as the record and can be read as one; the read-only report gives the number Andrew and the reviewers asked for at no risk. If the app later needs it, a stored kind can follow with its own label.
- **Re-score with a new actuals date.** Would mix two changes (new filings and new rules). The comparison holds the actuals fixed and compares only quarters whose actual is equal.

## Files to change

New `domains/evaluation/rescore.py`, `domains/evaluation/__main__.py` (command), new `tests/evaluation/test_rescore.py`, `domains/analysis/fresh_runs.py` (docstring on item 2), `docs/versions.md`, `docs/build-plan.md` (if a known gap changes), `docs/team-sync.md`.

## Product impact

None for the screens: no output, code, param or text the app reads is added, renamed or removed, and no stored number changes. The report is for the owner and the reviewers. One idea for the front-end (the professor's on #631): if the app ever shows the re-score, it must carry the label "calculado con las reglas de hoy (en retrospectiva)" and sit apart from the track record, which stays scored on the runs of the time (brief Q6).
