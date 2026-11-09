# Backlog #279: say when a margin quarter or a seed year sits on two bases

Issue: https://github.com/sonderbot-ar/warren/issues/279 · Branch `backlog-279-one-basis-follow-ups` · Version v0.9.44, merged nov.09.2026 (PR #291, merge `b876e80`; gatekeeper GO).

## Problem

v0.9.41 (#264) puts a derived quarter on one basis, one item at a time (`facts._Basis`). Its review left four follow-ups (the issue) and the gatekeeper two more (issue comment):

1. **Reported view vs run (product lead).** `reported_period` keeps the plain derivation, so JNJ FY2022Q4 revenue is 34,892 million there and 23,706 in a run.
2. **Per-item splits (analyst).** Revenue and EBIT are each put on one basis on their own, so a quarter's margin can divide a figure on one basis by a figure on another.
3. **Say it beside the margin (analyst).** When `one_basis` changes a quarter in the margin window, the operating margin's method doesn't say so; only the history row does.
4. **Seed across a basis break (analyst, professor).** After the fix, JNJ FY2022 has Q1–Q3 recast and Q4 as first filed; the revenue seed's year × share rule mixes them (24,693 million). Count it and say it in the seed's method.
5. **Tags (gatekeeper).** Pairing can match versions under different tags (AAPL FY2015Q4 D&A).
6. **Quarters no run reads (gatekeeper).** Spot-check them before another caller turns `one_basis` on.

This item does 2, 3 and 4: they are engine-only, change no number, and only make what the run already does visible. 5 is already written in #264's Limits ("Tags"), which was the gatekeeper's first option; nothing more here. 1 and 6 go together (turning the flag on in the reported view is the caller 6 warns about) and need the product lead's choice first; see Product impact.

## What "basis" means here

Every quarter fact the run reads gets one of four basis kinds (`math_engine.basis_kind`), from flags `get_facts(one_basis=True)` already sets (`Fact.restated`, `Fact.one_basis`, `Fact.mixed_vintage`). The rows are checked in this order; `mixed_vintage` implies `restated` (`facts._derive`), so a fact matches exactly one:

| Kind | When | Meaning (teach it as) |
|---|---|---|
| `first_filed` | `one_basis`, not `restated` | old basis: put back on the basis it was first reported on, because a newer version of an input was recast (#264 rule 3) |
| `restated` | `one_basis` and `restated`; or `restated`, not `mixed_vintage` | new basis: a reported quarter recast later, a derivation from recast inputs only, or #264 rule 2 |
| `no_basis` | `mixed_vintage`, not `one_basis` | no basis: derived from recast and unrecast inputs and left so (no one-basis version public) |
| `unchanged` | otherwise | not refiled: no second version public by the as-of date. It may still be on the old basis if no later filing has given it again yet (analyst) |

Two facts **sit on two bases** when one is `first_filed` and another `restated`: one was kept old while a newer basis exists, and the other is on that newer one. A `no_basis` fact is on no basis on its own, so it is a split too. An `unchanged` fact alone never triggers a note: no filing public by the as-of date says which basis it is on, and a rule that guesses (old basis when its last filing predates a recast sibling's) gave false positives on KO FY2019, JNJ FY2023 and CAT FY2017 (analyst). When a note fires, its `unchanged` facts are listed apart as `not_refiled` ("not given again since first reported, so possibly still on the old basis"), so the note never implies they are fine (JNJ FY2022 on 2023-11-01: Q1 and Q2 were later recast too).

**Words.** The code keeps `restated` (it is `Fact.restated`, Warren's flag for "the newest version differs from the first"). Text a student reads says "as first reported" and "as recast": most of these are reclassifications (ASC 205-20-45-3) or retrospective application of a new principle (ASC 250), not restatements, which ASC 250-10-20 and IAS 8 keep for corrections of errors (professor, review below).

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. The margin quarters (items 2 and 3).** In `_drivers`, for each of the 12 margin quarters, the facts checked are the quarter's revenue and the facts its EBIT is built from (`resolve("ebit")`: `operating_income`, or `pretax_income` and `interest_expense`):
  - the "quarters used" list in the quarterly `operating_margin` method marks a quarter with "(one basis)" when any of those facts is `one_basis` (item 3), after the existing "(fallback)" mark when both apply (e.g. "FY2018Q4 (fallback) (one basis)");
  - a quarter whose facts sit on two bases gets "(two bases)" instead, and one coded note `margin_quarter_two_bases`: params `period` (`FYyyyyQn`), `first_filed`, `restated`, `no_basis`, `not_refiled` (each a sorted list of canonical item names from the four above, possibly empty); English text, naming each non-empty group in that order, items joined by "and", underscores as spaces: "FY2017Q4's operating margin divides figures that are not on one basis: revenue as first reported; operating income as recast. It is one of the 12 quarters the quarterly margins average." A `no_basis` group reads "pretax income worked out from recast and unrecast figures together".
  No value changes. Tests (`tests/analysis/test_math_engine.py`): each kind on hand-built facts; `unchanged` beside either kind is no split, `no_basis` alone is; Test Corp with revenue and operating income recast in the 2019 10-Qs and operating income's FY2018 given again on the new basis in an amended 10-K (filed 2019-11-15), as of 2019-12-31: FY2018Q4 revenue is as first reported, operating income as recast, the margin is marked "(two bases)", the note has its params and text, and the margin is still the average of the history rows' ratios; revenue recast alone (the #264 fixture): "(one basis)", no note; Test Corp unrecast: no mark, no note; both codes are in `RUN_NOTE_CODES`.
  Exit: tests pass, ruff clean.
- **Step 2. The seed (item 4).** The seed is the last four reported revenue quarters; they span one or two fiscal years. For each such year whose four revenue quarters (Q1–Q4 of the year, as the run reads them, all present) sit on two bases, every seed row in that year starts its method with "FY2018's quarters are not on one basis (Q4 as first reported; Q1, Q2, Q3 as recast)", and the run gets one note per year, `seed_year_two_bases`: params `fiscal_year`, `first_filed`, `restated`, `no_basis`, `not_refiled` (sorted lists of `Qn`), `year_times_share` (true when the quarters differ from the year by more than the tolerance, so the seed is the year × each quarter's share and the mix also sets those shares). English text: "FY2018's revenue quarters are not on one basis: Q4 as first reported; Q1, Q2, Q3 as recast. The forecast grows from these quarters, and because they don't add up to the year it splits the year by their shares, so the mix also sets those shares." (the clause after "quarters" only when `year_times_share`; otherwise the sentence ends there). The seed rule is unchanged: choosing another rule is #265's work (like-for-like scoring), and changing it here would move forecasts on 17 run dates. Tests: the #264 fixture as of 2019-12-31 (seed FY2018Q4 and FY2019Q1–Q3; FY2018's Q1–Q3 recast, Q4 as first reported) gives the note with its params and text, the method words on every seed row in FY2018 (here only FY2018Q4) and none on FY2019's, and the seed value of the unchanged rule; only the Q3 10-Q recast (Q4 first reported, Q3 recast, Q1–Q2 never given again) lists Q1 and Q2 under `not_refiled` with their words; an unrecast company gives none.
  Exit: tests pass, ruff clean.
- **Step 3. Real data** (snapshot `warren-20261105T101750Z`). Scan every stored run date for both cases (899 dates: some dates hold two runs, e.g. a run and its rerun), and rebuild every stored baseline run on main and on the branch. Expect: every value identical to main; the only changes are the method text of quarterly `operating_margin` rows and seed rows, and the new notes, on the runs the scan names. Results below.
  Exit: as expected; every stored run still reproduces.

**Point in time.** No new query: the kinds come from facts `load_history` already read as of the run's date. **LLMs.** None. **Invariants.** No number changes; stored runs reproduce from their stored rows; `rebuild` of runs the scan names differs in method text and notes only.

## Scan before building (nov.09.2026)

`load_history` on all 899 stored run dates, the 12 margin quarters each (10,755 quarter-dates) and the seed years:

- 88 margin quarter-dates have a `one_basis` fact (item 3's mark).
- **Margin quarters on two bases:** one, KO FY2017Q4 (13 run dates from 2020-03-01): revenue `first_filed` (7,512 million, no later version of the year at or after the recast nine months), operating income `restated` (1,354, #264 rule 2 on the FY2018 10-K's year). No `no_basis` fact in any margin window. The analyst's three examples are not splits by this definition or are outside the window: XOM FY2018Q4's EBIT was never restated (`unchanged`); PG FY2015Q4 and WMT FY2011Q4 are outside the 12-quarter window of every stored run (as #264's Limits say).
- **Seed years on two bases:** JNJ FY2022 (6 run dates from 2023-11-01; Q3 `restated`, Q4 `first_filed`), KO FY2018 (6 from 2019-11-01; Q2–Q3 `restated`, Q4 `first_filed`), XOM FY2018 (5 from 2019-11-15; Q3 `restated`, Q4 `first_filed`): 17 run dates, the 17 #264 named.

## Results (nov.09.2026)

Rebuild of all 903 stored baseline runs on main and on the branch (snapshot `warren-20261105T101750Z`, as of each run's date): no errors on either. Main: 821 exact, 82 differ (the #264 runs, as v0.9.41 recorded). The branch adds differences only on those 82 runs and only in method text: the quarterly `operating_margin` method (656 rows, the 8 quarterly periods of each), now with "(one basis)" or "(two bases)" marks. No value or source differs from main on any run; the seed rows' new words sit on rows that already differ from their stored version since v0.9.41.

Notes on the rebuilt runs, matching the scan above:

| Code | Company, period | Runs | Params |
|---|---|---|---|
| `margin_quarter_two_bases` | KO FY2017Q4 | 13 | `first_filed` [revenue], `restated` [operating_income] |
| `seed_year_two_bases` | KO FY2018 | 6 | `first_filed` [Q4], `restated` [Q2, Q3], `not_refiled` [Q1], `year_times_share` true |
| `seed_year_two_bases` | XOM FY2018 | 5 | `first_filed` [Q4], `restated` [Q3], `not_refiled` [Q1, Q2], `year_times_share` true |
| `seed_year_two_bases` | JNJ FY2022 | 6 | `first_filed` [Q4], `restated` [Q3], `not_refiled` [Q1, Q2], `year_times_share` true |

Stored runs keep their stored rows and notes; a new run on these dates (after the next ingest, `_same_inputs`) gets the notes. Reproduce is unaffected (it values stored rows).

## Alternatives considered

- **Put all of a quarter's items on one basis together** (the #264 alternative "not now"). Still not now: for KO FY2017Q4 it would mean either taking revenue onto the 2018 basis (no filing gives that quarter's revenue on it) or taking operating income back to first filed (dropping the rule-2 figure the analyst confirmed). One quarter on 13 run dates, a note says it; the choice belongs with #265.
- **Change the seed rule on a broken year** (use the quarter's own value instead of year × share). Rejected here: it moves forecasts on 17 run dates and is a method choice for #265, which decides how scoring treats a change of basis.
- **Flags on the margin's sources instead of a note.** The margin's sources are pointers to history rows, which already carry `one_basis`; what the app can't see from them is that two items disagree, which is a statement about the quarter, so it is a note.
- **Count `unchanged` beside `first_filed` as a split.** Rejected: an item never restated has the same value on every basis the filings show; flagging it would put a note on XOM's runs for no difference.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `tests/analysis/test_math_engine.py`, this doc (`tests/analysis/test_build_warning_codes.py` already checks every warning code is in `RUN_NOTE_CODES`). At merge: `docs/versions.md`, `docs/team-sync.md`.

## Limits

- **A figure not yet refiled can still be old (analyst, professor).** `unchanged` only means no second version is public by the as-of date. So a split whose old-basis side is a figure not yet given again is not caught. The analyst found, by comparing with the history a year later, on stored run dates:
  - KO FY2018 seed, 3 run dates (2019-08-01 to 2019-10-01): Q2 recast (CCBA), Q3 and Q4 later recast too; quarters miss the year by +1.55%, so year × share runs on a mixed year without a note.
  - XOM FY2019 seed, 3 run dates (2020-06-01 to 2020-08-01): Q1 recast, Q2 later recast (67,491 → 69,091); gap −0.6%.
  - JNJ FY2023Q1 and Q2 margins, 7 quarter-dates from 2024-03-01: EBIT falls back to pretax + interest; revenue and pretax recast, interest expense later recast (Q2 346 → 217, about 0.6 points of margin).
  - JNJ FY2022 seed, 6 run dates: caught, but Q1 and Q2 are old basis too; the note lists them as `not_refiled`.
  No rule using only filings public by the as-of date separates these from the false positives above, so they stay documented, not flagged.
- **The seed stays as it is.** A practitioner would put a broken year on the newest basis in full (recast quarters as given, the rest scaled by the recast year-to-date) instead of year × share across bases; the note alone leaves JNJ FY2022's seed off by up to 4% (its quarters miss the year by −4.0%). That belongs with #265 (analyst).
- **No size.** The notes say that figures are on two bases, not by how much. A size (the first-reported vs recast gap, or the quarters' gap to the year) is an idea for the app's screen and #265.
- **The seed's four quarters only.** The note covers the years the seed reads; the margin window and the seed are the two places where quarters on different bases meet in one number.

## Design review (nov.09.2026)

Explainer, analyst, professor and product lead, as fresh-context subagents, on the first draft.

- **Analyst: NO-GO, one blocker, taken.** "`unchanged` fits either" was false on real data: `restated` means "differs from the first version public", so `unchanged` only means not refiled yet (facts.py `_facts`, `_derive`). Checked against the history a year later: JNJ FY2022 Q1–Q2 were still old basis beside the note; KO FY2018 and XOM FY2019 seeds (3 run dates each) and JNJ FY2023Q1–Q2 margins (7 quarter-dates) mix bases unnoticed. Taken: the definition rewritten; `not_refiled` added to both notes, listing such facts apart with words that say they may be old; the missed cases listed under Limits. The analyst's test rule (old when its last filing predates a recast sibling's) was rejected on the analyst's own evidence (false positives on KO FY2019, JNJ FY2023, CAT FY2017). Scan claims confirmed (KO FY2017Q4; 17 seed dates; XOM FY2018Q4 pretax refiled 2019-11-06 at the same value). Ideas: the practitioner's seed fix and JNJ's −4.0% gap noted for #265 under Limits; the `one_basis` and `restated` row made explicit in the table and tested; JNJ FY2022Q1–Q2 at 2023-11-01 goes to the item-6 spot-check issue.
- **Professor: NO-GO on wording, method GO; taken.** "Restated" / "reexpresada" is wrong for most cases (ASC 250-10-20 and NIC 8 keep it for error corrections; ASC 205-20-45-3 reclassification; NIC 29 inflation adjustment in Argentina). Student-facing text now says "as first reported" / "as recast", Spanish "presentación original" / "presentación nueva"; item names print as words. The seed note's English text is written out in full, with what `year_times_share` does to the forecast. Ideas taken: teach the kinds as old basis / new basis / no basis / not refiled; "ejercicio 2017" and "4.º trimestre" in Spanish. Idea not taken here: a size in the note (Limits). Idea for #265: pre-2021 10-Ks carried unaudited quarterly data (S-K Item 302(a)), which may give a later-basis Q4.
- **Product lead: GO, three gaps taken.** The item names that can occur are listed; a Spanish sentence for `no_basis` (and now `not_refiled`); a second Spanish sentence when `year_times_share`. Item 1: chose (b), recorded above.
- **Explainer: gaps, taken.** The kinds are checked in order and can't overlap; which facts count as EBIT's; how "(fallback)" and the basis marks combine; the text for each group and for several items; what the seed's "four quarters" are; the 899 vs 903 count; results section added; where the texts live.

## PR review (nov.09.2026)

- **Gatekeeper (on 1862aca): GO, no blockers.** pytest 1,982 passed, 1 skipped (Playwright); ruff clean; doc matches code; no value path changed; no new query; real-data spot check `KO_2020-03-01_1` gives the KO FY2017Q4 note as documented. Ideas taken: two docstrings still said `unchanged` "fits either" (now aligned with the analyst's reading); "Files to change" corrected; the seed-row wording in Step 2 (the test already checks FY2019's rows carry no words).

## Product impact

Two run-note codes added to `RUN_NOTE_CODES`, nothing renamed or removed. English texts are built in `math_engine` (`_basis_mark`, `_seed_basis_note`) as the fallback; the Spanish below is a suggestion for the app's catalogue, which owns the words.

- `margin_quarter_two_bases`: params `period` (`FYyyyyQn`), `first_filed`, `restated`, `no_basis`, `not_refiled`: sorted lists of item names, each one of `revenue`, `operating_income`, `pretax_income`, `interest_expense` (the app needs a Spanish label for each). Suggested Spanish (product lead and professor, review below; "reexpresado" avoided: under NIC 8 it means correcting an error, and in Argentina it reads as inflation-adjusted, NIC 29): "El margen operativo del 4.º trimestre del ejercicio 2017 divide la utilidad operativa con la presentación nueva (cifras reclasificadas o ajustadas por la empresa en un reporte posterior) entre los ingresos tal como se informaron originalmente. Es uno de los 12 trimestres que promedia el supuesto de margen." For a non-empty `no_basis`: "X se calculó con cifras de la presentación original y de la nueva a la vez." For a non-empty `not_refiled`: "X no se ha vuelto a informar desde su presentación original, así que puede seguir en la base anterior."
- `seed_year_two_bases`: params `fiscal_year`, `first_filed`, `restated`, `no_basis`, `not_refiled` (sorted lists of `Qn`), `year_times_share` (bool). Suggested Spanish: "Los trimestres del ejercicio 2018 de los que parte el pronóstico no están todos en la misma presentación: el 4.º tal como se informó originalmente, el 1.º al 3.º con la presentación nueva." When `year_times_share`: "Como el pronóstico reparte el año según el peso de cada trimestre, la mezcla también afecta ese reparto."

Brief questions: Q3 and Q5 (a run's value, assumptions and forecast) can explain these runs; values are unchanged. Q1–Q2, Q6: no change.

**Item 1, the reported view: the front-end team chose (b)** (product lead, review below): the engine returns the one-basis figure beside the plain derivation, with a code saying which is which; the screen shows the one-basis figure as the main number, so Q1 agrees with the run, and the plain one in the side panel with the reason, as Q1 already shows first-reported beside latest. The gatekeeper's spot-check of the quarters no run reads (item 6) comes first. Both go to #290 (`backlog`, `front-end`), not this PR.
