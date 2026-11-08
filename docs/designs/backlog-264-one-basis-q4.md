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
- **Step 1. Derive on one basis.** `get_facts(..., frequency="quarterly", one_basis=True)` (latest mode only; anything else raises `ValueError`). The rule (`facts._Basis`) applies to every derived quarter of a flow item: Q4 = year − nine months (or − Q1 − Q2 − Q3), Q3 = nine months − half (or − Q1 − Q2), Q2 = half − Q1, so it covers cash-flow items reported only year-to-date too.
  1. If no input of the derivation was ever restated (each newest version has the value first filed), it is kept: all inputs are as first filed, one basis. ("Restated" is today's `Fact.restated`: the newest version's value differs from the first-filed one.)
  2. Otherwise the minuend (the year, half or nine months) is taken as given by the **first filing at or after the newest subtracted input's vintage**, and the derivation uses it with the same subtracted inputs. An input's vintage is the first filing that gave its current value: a later 10-Q that only repeats last year's nine months doesn't move it (PG's FY2013 tax: 2,812 in both 10-Qs, the year recast for Pet Care in between; pairing on the repeat would give 579 on two bases, the vintage gives 629). A derived input's vintage is its `filed_at`. A version of the year with the opposite sign to the newest one is a tagging error a later filing corrected, not a basis (WMT's FY2009 and FY2010 tax, negative in 0001193125-11-083157, positive later), so it is skipped and the next version is paired. That pairs the year with the 10-K that follows the recast 10-Q, on that 10-Q's basis. It covers the mixed case once the next 10-K is out (JNJ FY2022 in runs dated 2024) and a year restated twice while the nine months were recast once (KO's FY2017 operating income, analyst, below).
  3. If no such filing is public yet (the old year from the 10-K, nine months recast in a later 10-Q: JNJ FY2022Q4 in Nov 2023), the quarter is derived from every input as first filed (the old year minus the old nine months). That is on one basis and every input was public earlier. If the first-filed facts give no derivation for the quarter, or the year as first filed has the opposite sign to the newest, the plain derivation is kept.
  A quarter whose value changes this way carries a new flag `Fact.one_basis = True`; its `inputs` name the filings used and its `filed_at` is the latest of them (never after `as_of`). Default `one_basis=False`: every other caller (the harness's actuals and comparatives, hindsight, the AI's history, the quality report, `reported_period`) is unchanged, so no stored evaluation number changes. Both modes come from one query (the rows are read once).
  `math_engine.load_history` asks for `one_basis=True`. A history row built this way says so in its method text: "derived from A, B (year and year-to-date taken on one basis: a newer version of one was restated)" (worded to be true under rule 2 and rule 3). Its filing source (`src.filing`) gains `one_basis` (true or false; absent on sources stored before this version, which means false), so the app can explain it without reading English.
  Tests (`tests/fundamentals/test_quarterly.py`): the old year minus the recast nine months is mixed without the flag (the defect); with it, Q4 is the old year minus the old nine months, flagged, not restated, public on the 10-K's date; a restated year with old nine months gives the old quarter too; a recast year with recast nine months is kept; a year restated twice is paired with the 10-K after the recast nine months, not the newest; a 10-Q that only repeats the old nine months doesn't move the pairing; a version of the year with the wrong sign is skipped, and a first-filed year with the wrong sign is no fallback; on unrecast data the flag changes nothing; a quarter with no first-filed derivation is kept; `one_basis` refuses first-reported or annual queries. `tests/analysis/test_math_engine.py`: a company whose 2019 10-Qs recast 2018's quarters 20% lower gets FY2018Q4 = the old fourth quarter in its run, with the method note and `one_basis` in its source, while Q1–Q3 keep their recast values. The seed's rule is unchanged and already tested; its new inputs show in the results below.
  Exit: tests pass, full suite green.
- **Step 2. Real data** (snapshot `warren-20261105T101750Z`). Rebuild every stored baseline run (903) on main and on this branch; count what changes; for changed runs with scored rows in the three stored batches, the baseline error before (stored) and after (the rebuilt rows valued again). Results below.
  Exit: main rebuilds all 903 runs exactly; on the branch every changed value is a derived history quarter put on one basis, or a row computed from one (the Q4 operating margin, the revenue seed); every changed run still reproduces from its stored rows.

**Point in time.** Both rules use only versions public on `as_of` (the paired minuend is one of them; the first-filed ones are older still); the derived value's `filed_at` is the latest of its inputs, never after `as_of`. **LLMs.** None. **Invariants.** Stored runs reproduce from their stored rows as before (`reproduce` values the rows, not the data). `rebuild` of the 82 affected stored runs now differs (history rows, margins, seeds), as after any change to how rows are built; their stored rows, outputs and scores stay as they are.

## Results (nov.08.2026)

Rebuild of all 903 stored baseline runs: main 903 of 903 exact; this branch 821 exact, 82 differ, none fail; all 82 still reproduce to the cent from their stored rows. The 82 are KO (28), XOM (20), JNJ (19) and CAT (15). The history rows that change are twelve item-quarters (values from the first stored run that holds the quarter, named where it matters; a later run can see a later filing):

| Company | Quarter, item | Before → after (million) | Why |
|---|---|---|---|
| JNJ | FY2022Q4 revenue | 34,892 → 23,706 | year from the 10-K before Kenvue, nine months from a 10-Q after |
| JNJ | FY2022Q4 EBIT (pretax + interest) | 6,383 → 4,378 (JNJ_2023-11-01) | same |
| JNJ | FY2021Q4 revenue | 9,769 → 24,804 (runs dated 2024) | FY2021 recast in the FY2023 10-K, nine months only as first reported |
| JNJ | FY2021Q4 EBIT | 1,298 → 4,896 | same |
| KO | FY2018Q4 revenue | 5,362 → 7,058 | 2019 10-Qs recast 2018 |
| KO | FY2018Q4 EBIT | 1,373 → 1,636 | same |
| KO | FY2017Q4 revenue | 8,314 → 7,512 (runs dated 2020) | FY2017 recast in the FY2019 10-K |
| KO | FY2017Q4 EBIT (operating income) | 1,510 → 1,354 (runs dated 2020) | year restated twice (7,501, 7,599, 7,755), nine months once (6,245): paired with the FY2018 10-K's 7,599 |
| KO | FY2016Q4 EBIT | 1,386 → 1,355 | FY2016 recast in a later 10-K |
| XOM | FY2018Q4 revenue | 61,015 → 68,253 | 2019 10-Qs recast 2018 |
| XOM | FY2017Q4 revenue | 72,513 → 65,312 (runs dated 2020) | FY2017 recast in the FY2019 10-K |
| CAT | FY2016Q4 EBIT | −598 → −1,262 | FY2016 restated in a later 10-K (pension accounting); Q4 2016 as filed was −1,262 |

At the level of `get_facts(one_basis=True)` about 55 item-quarters change across the 899 run dates (tax, capex, interest, D&A and amortisation too, e.g. CAT FY2014Q4 operating income −951 → 1,063, AAPL FY2015Q4 D&A 1,062 → 3,119); most sit outside the twelve quarters a run reads, which is why only these twelve history rows change. Every "after" is on one basis: the quarter as the company first filed it (year minus nine months, both as first filed), except KO FY2017Q4 EBIT, which is on the basis of the 2018 10-Q and the 10-K after it.

Other rows that move with them: the Q4 operating margin (164 rows, two per run) and the revenue seed (17 runs). The seed keeps its rule: when a year's four quarters don't add up to the year, it uses the year × the quarter's share. With the old fourth quarter beside recast first three, JNJ's seed for FY2022Q4 becomes 24,693 million (was 32,372), KO's 6,838 (5,478), XOM's 67,667 (62,086).

Effect on the scored baseline rows of the stored batches (the stored rows don't change; this is what the same runs would score if built today). Errors are as the harness stores them: revenue, absolute error over the actual; EBIT, absolute error over the actual's revenue, in points; the table gives the plain mean over the rows whose forecast moves.

| Batch | Scored baseline rows | Forecasts that move | Revenue error, mean of moved rows | EBIT error (pts of revenue), mean of moved rows |
|---|---|---|---|---|
| `eval_2026-11-02_1` (M8) | 208 | 4 (EBIT) | — | 39.6 → 40.4 |
| `eval_2026-11-03_1` (grid) | 852 | 19 | 35.4% → 20.4% (6 rows, 4 better) | 10.7 → 11.8 (13 rows, 4 better) |
| `eval_2026-11-03_2` (grid) | 916 | 19 | same rows | same rows |

- Better: JNJ FY2023Q4 revenue 59.1% → 21.4% (JNJ_2023-11-15, JNJ_2024-02-15), KO FY2019Q4 revenue 45.8% → 32.4% (two runs), KO's FY2019Q4 EBIT 13.3 → 11.3 points.
- Worse: XOM FY2019Q4 revenue 1.3% → 7.5% (XOM_2019-11-15, XOM_2020-02-15), JNJ FY2023Q4 EBIT 1.0 → 4.7 points, CAT FY2019Q4 EBIT 7.2 → 9.9 points. In each, the old-basis quarter is the figure the company filed, and the actual is on the new basis: the no-basis number had happened to sit nearer the new basis. What is left of these misses is the company's change of basis, which v0.9.37 already flags apart (`basis_change`), and which #265 (like-for-like scoring) is for.

So the fix removes Warren's own error where it was large (JNJ, KO revenue) and leaves real changes of basis visible as such. It does not make every number closer: a number on no basis can be close by accident.

## Limits

- **Per item, not per quarter.** Each item is put on one basis on its own, so a quarter's revenue and EBIT can sit on different bases in its margin. Seen: XOM FY2018Q4 (revenue falls back, EBIT unchanged; under 0.1 point on XOM's FY2019Q4 EBIT); the analyst's scan also found PG FY2015Q4 and WMT FY2011Q4 in runs dated 2019-04-01, outside the 12-quarter margin window. Filed as a follow-up.
- **A year on two bases across quarters.** After the fix, JNJ's FY2022 has Q1–Q3 on the post-Kenvue basis (from the 2023 10-Qs) and Q4 as first filed. The break moved from inside one quarter to between quarters; the seed's year × share rule then mixes them (24,693 million), and the series' seasonality reads across the break (Croushore 2011 on benchmark revisions). The remaining miss on JNJ FY2023Q4 (21%) is the change of basis itself, which #265 is for.
- **Subtracted inputs among themselves.** For Q4 = year − Q1 − Q2 − Q3, the three quarters can come from different 10-Qs; the rule pairs the year with the newest of them only.
- **Tags.** A filing's version of the year is its best tag in that filing, not "best tag first" across filings, so rule 2 can pair across tags (AAPL FY2015Q4 D&A 1,062, two tags mixed, becomes 3,119, one tag). No stored run reads such a row.
- **A real change of sign.** A version of the year with the opposite sign to the newest is treated as a tagging error and skipped; a genuine sign change in a restatement would be skipped too, and the next version (or the plain derivation) used. The newest version is the reference, so a wrong sign in the newest filing itself is not caught (WMT FY2008 tax, #280).
- **Other items.** `get_facts(one_basis=True)` changes about 55 item-quarters across the run dates, most of them items no run reads by quarter (tax, D&A, capex). Spot-check them before another caller turns the flag on.
- **The reported view.** `reported_period` (brief Q1–Q2) keeps the plain derivation with its `mixed_vintage` note, so JNJ's FY2022Q4 shows 34,892 million there and 23,706 in a run's history. Filed as a follow-up.
- **Stored runs keep their rows.** The pipeline reuses a stored run until the next ingest (`_same_inputs` checks the ingest, the concept map, the market downloads and the choices, not the code). After the next `fundamentals ingest`, a new run on these dates gets the fix. M10's grid runs were built on Nov 3 and are scored as stored (the AI's shocks were sized on them).

## Alternatives considered

- **Always derive from first-reported inputs.** Rejected: it throws away a recast year with recast nine months, which is on one (newer) basis and nearer what the actuals will be on.
- **Rescale the old fourth quarter to the new basis** (e.g. by the ratio of recast to old nine months). Rejected: it invents a number no filing gives; a business moved out does not shrink every quarter in proportion.
- **Change `get_facts` for every caller.** Rejected: the harness's comparatives and hindsight would change, and with them stored evaluation numbers and the v0.9.37 flag. Those callers already treat a mixed comparative as unknown, which is right for them.
- **Put all of a quarter's items on one basis together.** Not now: it needs the items grouped across canonical names; noted under Limits.
- **Pair only mixed derivations** (the first draft: a `mixed_vintage` quarter derived from first-filed inputs, everything else kept). Replaced after the analyst's review: it missed a year restated twice with the nine months restated once, and kept a no-basis KO FY2017Q4 operating income (1,510 million, margin 20.1% against 17.6% on one basis).

## Files to change

`domains/fundamentals/facts.py`, `domains/fundamentals/schemas.py`, `domains/analysis/math_engine.py`, `domains/analysis/sources.py`, `tests/fundamentals/test_quarterly.py`, `tests/analysis/test_math_engine.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

One field added, nothing renamed or removed: a filing source (`sources` of a run's row, `kind: "filing"`) gains `one_basis` (bool; missing on sources stored before this version, read as false). When true, the quarter was worked out from versions of the year and the year-to-date figure that share one basis (usually both as first filed; under rule 2, the year from the 10-K after the recast year-to-date), because a newer version of one of them was restated. Suggested Spanish: "calculado con cifras sobre una misma base: una versión más reciente de una de ellas se reexpresó". The method text (English, for the trace) says the same.

Brief questions: Q3 (a run's value and its assumptions) and Q5 (the forecast and its range) give, on new runs for the dates above, a forecast built on one basis. Q1–Q2 (reported figures) are unchanged: `reported_period` still shows the plain derivation with its `mixed_vintage` note, so a screen showing both may show two figures for the same quarter (JNJ FY2022Q4: 34,892 in the reported view, 23,706 in the run). Until the follow-up lands, the app can say the run's figure is worked out on one basis (the `one_basis` source). Q6 (track record) and run ranges read stored rows and don't change.

## Design review (nov.08.2026)

Explainer, analyst, professor and product lead, as fresh-context subagents, on the first draft.

- **Analyst: one blocker, taken.** The "two restatements" case does occur: KO's FY2017 operating income was restated twice (7,501, 7,599, 7,755) and its nine months once (6,245), so the first draft kept a Q4 of 1,510 on no basis and, with revenue falling back, raised the Q4 margin to 20.1% (17.6% on one basis). Taken: the rule now pairs the year with the first filing after the newest subtracted input's, as the analyst suggested (Step 1, rule 2); KO FY2017Q4 is 1,354; test added. Spot-checks of JNJ, KO and CAT matched. Ideas filed: a check or note for per-item basis splits; the same note on the Q4 operating margin row; the seed's basis break counted.
- **Professor: GO, no blockers.** Defensible as real-time vintage practice (Croushore and Stark 2001; Croushore 2011) and with ASC 205-20-45-3 and ASC 250-10-45-5 (a 10-Q never presents last year in full, so no new-basis Q4 exists until the next 10-K). Taken: the year-on-two-bases limit added; the method note reworded without "basis"; `_one_basis`'s silent KeyError path replaced by an explicit keep, with a test. Idea for #265: a free source for recast 8-K exhibits.
- **Product lead: three blockers, taken.** The app couldn't tell when the fallback was used (method text is English only): `one_basis` added to the filing source. The reported view and the run disagree on the same quarter: stated above, follow-up filed. The doc named the wrong questions (Q1–Q2 instead of Q3 and Q5): corrected.
- **Explainer: gaps, taken.** "Restated" defined; which derivations the rule covers (cash-flow Q2 and Q3 too); the missing first-filed case; the seed rows; the runs behind "two runs"; how errors are measured; reproduce run on the 82 (all pass).

## PR review (nov.08.2026)

- **Analyst (re-check on PR #278): two blockers, taken.** Scanning every run date at the `get_facts` level, the pairing rule (rule 2) ran on four item-quarters: KO FY2017 operating income (1,354, right), PG FY2014Q4 tax (593, plausible), and two wrong ones that reach no stored run: PG FY2013Q4 tax (paired on a 10-Q that only repeated the old nine months, then a 10-K recast the year: 579 on two bases; first filed 629) and WMT FY2009Q4 tax (paired with a 10-K that tagged the year −7,156, corrected later: −12,313; main had 1,999). Taken: an input is dated by the first filing of its value; a paired year of the opposite sign is refused. PG FY2013Q4 is now 629 and WMT FY2009Q4 1,925 (every input as first filed); KO stays 1,354. Two tests added. The 82 changed runs and the scored effect are identical to before the fix.
- **Analyst (second re-check): one blocker, taken.** With the sign check refusing the paired year, the fallback took the first-filed year, which held the same wrong sign: WMT FY2010Q4 tax −12,864 million (main 2,294; outside every stored run's window). Taken: a wrong-sign version is skipped and the next one paired (WMT FY2009Q4 and FY2010Q4 tax now equal main's 1,999 and 2,294), and a first-filed year of the wrong sign is never a fallback. Two tests. The 82 changed runs are again identical.
- **Gatekeeper (on ee8276d): one blocker, taken.** Tests 1,857 passed, ruff clean; point in time holds (every changed quarter's `filed_at` ≤ `as_of` across 448 queries, 1,547 changed quarters); stored history rows match main except the six revenue changes in the table. Blocker: the method note said "both as first filed", untrue under rule 2 (KO FY2017Q4 operating income uses the year's second version). Taken: the note, the schema description, the source comment and the suggested Spanish now say "on one basis"; a test checks the note on the rule-2 path. Ideas added to Limits (pairing across tags, a real change of sign, the other items).

