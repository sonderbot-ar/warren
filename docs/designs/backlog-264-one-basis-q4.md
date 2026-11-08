# Backlog #264: a derived quarter is built on one basis

Issue: https://github.com/sonderbot-ar/warren/issues/264 · Branch `backlog-264-one-basis-q4`.

## Problem

Companies never file a fourth quarter on its own: Warren works it out as the year minus the nine months (or minus the first three quarters). It does the same for a cash-flow Q2 or Q3 reported only year-to-date. For each input it takes the newest version public on the as-of date.

When a company recasts last year in a 10-Q (a business moved to discontinued operations, a new accounting rule applied to the comparatives), the 10-Q gives last year's nine months on the new basis, but the year itself is only in the old 10-K until the next 10-K. The year minus the recast nine months is then on no basis. The run's history row holds that number and the forecast grows from it.

- **JNJ_2023-11-15.** FY2022Q4 revenue 34,892 million: FY2022 from the 10-K (0000200406-23-000016, before Kenvue) minus nine months from the Q3 2023 10-Q (0000200406-23-000102, after Kenvue). JNJ reported 23,706 million at the time, 19,939 million on the new basis. The run forecasts 34,038 million for FY2023Q4: a 59% miss that is Warren's own.
- **KO_2019-11-15.** FY2018Q4 revenue 5,362 million (filed 7,058 million). **XOM_2019-11-15.** FY2018Q4 revenue 61,015 million (filed 68,253 million).

Everything used was public on the case date, so this is not look-ahead: the engine took its inputs from two bases. `Fact.mixed_vintage` already marks such a derivation (some inputs restated, some not), but nothing acted on it except the harness's comparative check.

## Plan

- **Step 0.** This design doc.
- **Step 1. Derive on one basis.** `get_facts(..., frequency="quarterly", one_basis=True)` (latest mode only; anything else raises `ValueError`). For each item and fiscal year, the quarters are derived as today; a derived quarter that is `mixed_vintage` is replaced by the same quarter derived from every input as first reported (the old year with the old nine months). That version shares one basis and was public by the same date (its inputs are older). It carries a new flag `Fact.one_basis = True`, `restated = False`, and its `inputs` name the old filings. A derivation whose inputs were all restated (the recast year with the recast nine months, once the next 10-K is public) is not mixed and is kept. Default `one_basis=False`: every other caller (the harness's actuals and comparatives, hindsight, the AI's history, the quality report) is unchanged, so no stored evaluation number changes. Both modes come from one query (the rows are read once).
  `math_engine.load_history` asks for `one_basis=True`. A history row built this way says so in its method text: "derived from A, B (all as first reported: the newest inputs were on two bases)". Its sources (`src.filing`) are unchanged in shape and name the old filings.
  Tests (`tests/fundamentals/test_quarterly.py`): the old year minus the recast nine months is mixed without the flag (the defect); with it, Q4 is the old year minus the old nine months, flagged, not restated, public on the 10-K's date; a restated year with old nine months falls back too; a recast year with recast nine months is kept; on unrecast data the flag changes nothing; `one_basis` refuses first-reported or annual queries. `tests/analysis/test_math_engine.py`: a company whose 2019 10-Qs recast 2018's quarters 20% lower gets FY2018Q4 = the old fourth quarter in its run, with the method note, while Q1–Q3 keep their recast values.
  Exit: tests pass, full suite green.
- **Step 2. Real data** (snapshot `warren-20261105T101750Z`). Rebuild every stored baseline run (903) on main and on this branch; count what changes; for changed runs with scored rows in the three stored batches, the baseline error before (stored) and after (the rebuilt rows valued again). Results below.
  Exit: main rebuilds all 903 runs exactly; every change on the branch is a derived quarter that was mixed, or a row computed from one.

**Point in time.** The fallback uses only first-reported versions, each public before the newest one; the derived value's `filed_at` is the latest of its inputs, never after `as_of`. **LLMs.** None. **Invariants.** Stored runs reproduce from their stored rows as before (`reproduce` values the rows, not the data). `rebuild` of the 82 affected stored runs now differs (history rows, margins, seeds), as after any change to how rows are built; their stored rows, outputs and scores stay as they are.

## Results (nov.08.2026)

Rebuild of all 903 stored baseline runs: main 903 of 903 exact; this branch 821 exact, 82 differ, none fail. The 82 are KO (28), XOM (20), JNJ (19) and CAT (15). The history rows that change are eleven item-quarters (values from the first stored run that holds the quarter, named where it matters; a later run can see a later filing):

| Company | Quarter, item | Before → after (million) | Why |
|---|---|---|---|
| JNJ | FY2022Q4 revenue | 34,892 → 23,706 | year from the 10-K before Kenvue, nine months from a 10-Q after |
| JNJ | FY2022Q4 EBIT (pretax + interest) | 6,383 → 4,378 (JNJ_2023-11-01) | same |
| JNJ | FY2021Q4 revenue | 9,769 → 24,804 (runs dated 2024) | FY2021 recast in the FY2023 10-K, nine months only as first reported |
| JNJ | FY2021Q4 EBIT | 1,298 → 4,896 | same |
| KO | FY2018Q4 revenue | 5,362 → 7,058 | 2019 10-Qs recast 2018 |
| KO | FY2018Q4 EBIT | 1,373 → 1,636 | same |
| KO | FY2017Q4 revenue | 8,314 → 7,512 (runs dated 2020) | FY2017 recast in the FY2019 10-K |
| KO | FY2016Q4 EBIT | 1,386 → 1,355 | FY2016 recast in a later 10-K |
| XOM | FY2018Q4 revenue | 61,015 → 68,253 | 2019 10-Qs recast 2018 |
| XOM | FY2017Q4 revenue | 72,513 → 65,312 (runs dated 2020) | FY2017 recast in the FY2019 10-K |
| CAT | FY2016Q4 EBIT | −598 → −1,262 | FY2016 restated in a later 10-K (pension accounting); Q4 2016 as filed was −1,262 |

In every row the "after" is the quarter the company filed at the time (its year minus its nine months, both as first published).

Other rows that move with them: the Q4 operating margin (164 rows, two per run) and the revenue seed (17 runs). The seed keeps its rule: when a year's four quarters don't add up to the year, it uses the year × the quarter's share. With the old fourth quarter beside recast first three, JNJ's seed for FY2022Q4 becomes 24,693 million (was 32,372), KO's 6,838 (5,478), XOM's 67,667 (62,086).

Effect on the scored baseline rows of the stored batches (the stored rows don't change; this is what the same runs would score if built today):

| Batch | Scored baseline rows | Forecasts that move | Revenue error, mean of moved rows | EBIT error (pts of revenue), mean of moved rows |
|---|---|---|---|---|
| `eval_2026-11-02_1` (M8) | 208 | 4 (EBIT) | — | 39.6 → 40.4 |
| `eval_2026-11-03_1` (grid) | 852 | 19 | 35.4% → 20.4% (6 rows, 4 better) | 10.7 → 11.8 (13 rows, 5 better) |
| `eval_2026-11-03_2` (grid) | 916 | 19 | same rows | same rows |

- Better: JNJ FY2023Q4 revenue 59.1% → 21.4% (two runs), KO FY2019Q4 revenue 45.8% → 32.4% (two runs), KO's FY2019Q4 EBIT 13.3 → 11.3 points.
- Worse: XOM FY2019Q4 revenue 1.3% → 7.5% (two runs), JNJ FY2023Q4 EBIT 1.0 → 4.7 points, CAT FY2019Q4 EBIT 7.2 → 9.9 points. In each, the old-basis quarter is the figure the company filed, and the actual is on the new basis: the no-basis number had happened to sit nearer the new basis. What is left of these misses is the company's change of basis, which v0.9.37 already flags apart (`basis_change`), and which #265 (like-for-like scoring) is for.

So the fix removes Warren's own error where it was large (JNJ, KO revenue) and leaves real changes of basis visible as such. It does not make every number closer: a number on no basis can be close by accident.

## Limits

- **Per item, not per quarter.** Each item is put on one basis on its own. A quarter whose revenue falls back but whose EBIT inputs were all restated (or none were) can have revenue and EBIT on different bases in its margin. On today's data this happens for XOM FY2018Q4 (revenue falls back, EBIT unchanged); its effect on XOM's FY2019Q4 EBIT is under 0.1 point.
- **Two restatements.** If both inputs were restated, but by different filings on different bases, `mixed_vintage` doesn't see it (it only compares with first-reported). Not seen on the eight companies.
- **Stored runs keep their rows.** The pipeline reuses a stored run until the next ingest (`_same_inputs` checks the ingest, the concept map, the market downloads and the choices, not the code). After the next `fundamentals ingest`, a new run on these dates gets the fix. M10's grid runs were built on Nov 3 and are scored as stored (the AI's shocks were sized on them).

## Alternatives considered

- **Always derive from first-reported inputs.** Rejected: it throws away a recast year with recast nine months, which is on one (newer) basis and nearer what the actuals will be on.
- **Rescale the old fourth quarter to the new basis** (e.g. by the ratio of recast to old nine months). Rejected: it invents a number no filing gives; a business moved out does not shrink every quarter in proportion.
- **Change `get_facts` for every caller.** Rejected: the harness's comparatives and hindsight would change, and with them stored evaluation numbers and the v0.9.37 flag. Those callers already treat a mixed comparative as unknown, which is right for them.
- **Put all of a quarter's items on one basis together.** Not now: it needs the items grouped across canonical names; noted under Limits.

## Files to change

`domains/fundamentals/facts.py`, `domains/fundamentals/schemas.py`, `domains/analysis/math_engine.py`, `tests/fundamentals/test_quarterly.py`, `tests/analysis/test_math_engine.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

No call, field, code or note the app reads is added, renamed or removed. A new run's history row for a derived quarter can carry a longer method text ("all as first reported: the newest inputs were on two bases") and name older filings in its sources; the app shows sources as they come. Brief questions served: Q1–Q2 (a run's forecast and its sources) on the dates above give a forecast built on one basis. The track record (Q6) and run ranges read stored rows and don't change.
