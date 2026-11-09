# Backlog #279: say when a margin quarter or a seed year sits on two bases

Issue: https://github.com/sonderbot-ar/warren/issues/279 · Branch `backlog-279-one-basis-follow-ups` · Status: in progress (nov.09.2026).

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

Every quarter fact the run reads gets one of four basis kinds, from flags `get_facts(one_basis=True)` already sets (`Fact.restated`, `Fact.one_basis`, `Fact.mixed_vintage`):

| Kind | When | Meaning |
|---|---|---|
| `first_filed` | `one_basis` and not `restated` | put back on the basis it was first filed on, because a newer version of one input was restated (#264 rule 3) |
| `restated` | `restated` and not (`mixed_vintage` without `one_basis`) | on a newer basis than first filed: a reported quarter whose newest version was restated, a derivation whose inputs were all restated, or #264 rule 2 |
| `none` | `mixed_vintage` and not `one_basis` | derived from restated and unrestated inputs and left so (no one-basis version public) |
| `unchanged` | not `restated`, not `one_basis` | never restated: the same on any basis the filings show |

Two facts **sit on two bases** when one is `first_filed` and another `restated`: one was deliberately kept old while a newer basis exists, and the other is on that newer one. `unchanged` fits with either, so it never makes a split (XOM FY2018Q4: revenue `first_filed`, EBIT never restated, one basis as far as the filings show). A `none` fact is on no basis on its own.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. The margin quarters (items 2 and 3).** `math_engine.basis_kind(fact)` returns the kind above. In `_drivers`, for each of the 12 margin quarters:
  - the "quarters used" list in the quarterly `operating_margin` method marks a quarter whose revenue or any EBIT fact is `one_basis` with "(one basis)", beside the existing "(fallback)" mark (item 3);
  - a quarter whose revenue and EBIT facts sit on two bases, or include a `none` fact, gets one coded note `margin_quarter_two_bases`, params `period` (`FYyyyyQn`), `first_filed` (canonical item names, sorted), `restated` (same), `no_basis` (same; usually empty), and the English text "FY2017Q4's operating margin divides figures on two accounting bases: revenue as first filed, operating_income restated. The quarter is one of the 12 the quarterly margins average." The mark in the method is "(two bases)" instead of "(one basis)".
  No value changes. Tests (`tests/analysis/test_math_engine.py`, `test_build_warning_codes.py`): the kinds on hand-built facts (each row of the table, and `unchanged` beside either kind is no split); on Test Corp with revenue recast in the 2019 10-Qs and operating income recast there and in a later filing of the year, FY2018Q4's margin is marked "(two bases)" and carries the note with its params; with revenue recast alone (the #264 fixture) it is marked "(one basis)" with no note; every margin and every value is the same as without the change; the new code is in `RUN_NOTE_CODES`.
  Exit: tests pass, ruff clean.
- **Step 2. The seed (item 4).** In `_revenue_seed`, for each fiscal year among the four seed quarters, if its four quarters (as the run reads them) sit on two bases, the seed rows of that year say so in their method ("FY2022's quarters sit on two bases: Q4 as first filed, Q3 restated; …"), and the run gets one coded note per year, `seed_year_two_bases`, params `fiscal_year`, `first_filed` and `restated` (quarter labels `Qn`, sorted), `year_times_share` (true when the year × share rule ran for the year, so the mixed quarters also set the shares), and English text. The seed rule is unchanged: choosing another rule is #265's work (like-for-like scoring), and changing it here would move forecasts. Tests: the #264 fixture (Q1–Q3 recast, Q4 as first filed) gives the note and the method words for FY2018, `year_times_share` true when the year differs; a year all `unchanged` or all `restated` gives none; values unchanged.
  Exit: tests pass, ruff clean.
- **Step 3. Real data** (snapshot `warren-20261105T101750Z`). Scan every stored run date (899) for both cases, and rebuild all 903 stored runs on main and on the branch. Expect: every value identical to main; the only changes are the method text of quarterly `operating_margin` rows and seed rows, and the new notes, on the runs the scan names. Results below.
  Exit: as expected; every stored run still reproduces.

**Point in time.** No new query: the kinds come from facts `load_history` already read as of the run's date. **LLMs.** None. **Invariants.** No number changes; stored runs reproduce from their stored rows; `rebuild` of runs the scan names differs in method text and notes only.

## Scan before building (nov.09.2026)

`load_history` on all 899 stored run dates, the 12 margin quarters each (10,755 quarter-dates) and the seed years:

- 88 margin quarter-dates have a `one_basis` fact (item 3's mark).
- **Margin quarters on two bases:** one, KO FY2017Q4 (13 run dates from 2020-03-01): revenue `first_filed` (7,512 million, no later version of the year at or after the recast nine months), operating income `restated` (1,354, #264 rule 2 on the FY2018 10-K's year). No `none` fact in any margin window. The analyst's three examples are not splits by this definition or are outside the window: XOM FY2018Q4's EBIT was never restated (`unchanged`); PG FY2015Q4 and WMT FY2011Q4 are outside the 12-quarter window of every stored run (as #264's Limits say).
- **Seed years on two bases:** JNJ FY2022 (6 run dates from 2023-11-01; Q3 `restated`, Q4 `first_filed`), KO FY2018 (6 from 2019-11-01; Q2–Q3 `restated`, Q4 `first_filed`), XOM FY2018 (5 from 2019-11-15; Q3 `restated`, Q4 `first_filed`): 17 run dates, the 17 #264 named.

## Alternatives considered

- **Put all of a quarter's items on one basis together** (the #264 alternative "not now"). Still not now: for KO FY2017Q4 it would mean either taking revenue onto the 2018 basis (no filing gives that quarter's revenue on it) or taking operating income back to first filed (dropping the rule-2 figure the analyst confirmed). One quarter on 13 run dates, a note says it; the choice belongs with #265.
- **Change the seed rule on a broken year** (use the quarter's own value instead of year × share). Rejected here: it moves forecasts on 17 run dates and is a method choice for #265, which decides how scoring treats a change of basis.
- **Flags on the margin's sources instead of a note.** The margin's sources are pointers to history rows, which already carry `one_basis`; what the app can't see from them is that two items disagree, which is a statement about the quarter, so it is a note.
- **Count `unchanged` beside `first_filed` as a split.** Rejected: an item never restated has the same value on every basis the filings show; flagging it would put a note on XOM's runs for no difference.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `tests/analysis/test_math_engine.py`, `tests/analysis/test_build_warning_codes.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Two run-note codes added to `RUN_NOTE_CODES`, nothing renamed or removed:

- `margin_quarter_two_bases`: params `period`, `first_filed`, `restated`, `no_basis` (lists of canonical item names). Suggested Spanish: "El margen operativo de FY2017Q4 divide cifras en dos bases contables: los ingresos tal como se presentaron por primera vez y la utilidad operativa reexpresada."
- `seed_year_two_bases`: params `fiscal_year`, `first_filed`, `restated` (lists of `Qn`), `year_times_share` (bool). Suggested Spanish: "Los trimestres de FY2022 de los que parte el pronóstico están en dos bases contables: Q4 tal como se presentó por primera vez y Q3 reexpresado."

Brief questions: Q3 and Q5 (a run's value, assumptions and forecast) can explain these runs; values are unchanged. Q1–Q2: no change.

**For the product lead (item 1, not built here).** The reported view (`reported_period`, brief Q1–Q2) shows the plain derivation with its `mixed_vintage` note. Options: (a) keep it, and add a code saying the run uses another figure for that quarter; (b) show the one-basis figure beside the plain one, with a code saying which is which; (c) show only the one-basis figure. (b) and (c) turn `one_basis` on for a caller that reads every item and quarter, so the gatekeeper's spot-check of those quarters (item 6; e.g. MSFT FY2017Q4 pretax 1,206 → 5,545) comes first. The choice is the front-end team's; it gets its own issue.
