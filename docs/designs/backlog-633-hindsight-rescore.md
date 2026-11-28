# Backlog #633: a hindsight re-score of the monthly forecasts on the fresh runs

Issue: https://github.com/sonderbot-ar/warren/issues/633 · Branch `claude/project-thread-8md91m` (the cloud run's assigned branch) · Version v0.10.61 when merged.

Status: In progress (nov.28.2026). PR open; gatekeeper next.

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

## Results (Step 2, nov.28.2026)

On the restored snapshot `warren-20261128T052153Z` (the 914 fresh runs of v0.10.60), actuals as first reported by 2026-11-27. Scored with today's rules (hindsight), so not the forecast record. Full tables: `data/reports/eval/rescore_hindsight.md` (git-ignored; `python -m domains.evaluation rescore` writes it again in about two minutes).

- **728 of 728 origins re-scored, none failed;** 5,542 quarter rows compared (2,771 per item, 247 distinct company quarters); 282 rows not compared because the run of the time had them missing or excluded. No compared row had a differing actual.
- **Revenue: a little better.** Mean absolute error 10.67% to 10.60%; 11 rows moved, 8 better and 3 worse, all at h1 (h1 mean 10.69% to 10.44%). The gains are J&J and Coca-Cola: J&J's FY2023Q4 forecast from 2023-11-01 and 2023-12-01 missed by 46.4% and now by 19.4%, because the year-ago quarter it grows from (FY2022Q4) was read as 34.9B and is now 23.7B, the quarter as filed; Coca-Cola's FY2019Q4 from 2019-11-01 and 2019-12-01 missed by 61.3% and now by 39.1% (FY2018Q4 5.36B, now 7.06B as filed). Exxon's three rows got worse (FY2019Q4 from +1.4% to −7.3%), on a corrected FY2018Q4 (61.0B to 68.3B): the right year-ago figure gave a worse forecast that quarter.
- **Operating profit: slightly worse.** Mean absolute error 5.42 to 5.44 margin points; 65 rows moved, 7 better and 58 worse, by 1.0 point on average on the moved rows. Caterpillar (11 worse; FY2016Q4 operating profit read −598M before, −1,262M now, the loss with its restructuring and pension charges) and J&J (16 worse) carry most of it. Every move is in a fourth quarter, whose margin forecast is built from the same quarter in earlier years: the fixes read those fourth quarters right, and a right figure that holds one-off charges is a worse guide to next year's quarter than a wrong one that happened to look normal.
- **Everything else the fixes changed (tax rate, debt, working capital, the cost of debt) moves value, not the revenue and operating-profit forecasts this scores.** Apple, Microsoft, P&G and Walmart: no row moved.
- **Stored drift: 46 rows** (Apple 24, Caterpillar 22), all quarters stored as missing whose actual has been filed since; not a code difference. They are outside the comparison, which scores both runs today.
- **No significance test**, by design (see Step 1). The 11 moved revenue rows are 3 distinct quarters (J&J FY2023Q4, Coca-Cola and Exxon FY2019Q4) and the 65 operating-profit rows are 7 (Caterpillar FY2019Q4, J&J FY2023Q4 and FY2024Q4, Coca-Cola and Exxon FY2019Q4 and FY2020Q4), so the numbers describe a small change, nothing more.
- `python -m domains.analysis reproduce --all` and `ranges reproduce` on the newest build: 1,850 of 1,850 runs reproduce to the cent, and `ranges_2026-11-25_1` checks 5,496 errors and 15,664 ranges OK; nothing stored moved.

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
