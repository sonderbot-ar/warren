# Backlog #324: a reported quarter under a narrower tag than its year

Issue: https://github.com/sonderbot-ar/warren/issues/324 · Branch `backlog-324-quarter-tags` · Status: built, PR open (nov.11.2026).

## Problem

Walmart's 10-Ks of 2011-03-30 ([0001193125-11-083157](https://www.sec.gov/Archives/edgar/data/104169/000119312511083157/)) and 2012-03-27 ([0001193125-12-134679](https://www.sec.gov/Archives/edgar/data/104169/000119312512134679/)) give the fourth quarter only in the quarterly-data note, tagged `us-gaap:SalesRevenueNet` (net sales). The year (`us-gaap:Revenues`, total revenues: net sales plus membership and other income) and every 10-Q's quarter and nine months use `Revenues`. (The concept map, `domains/fundamentals/concept_map.csv`, ranks the tags of each item: for revenue `Revenues` 1, the contract-revenue tag 2, `SalesRevenueNet` 3.) A reported quarter beats a derived one, so Warren shows (snapshot of nov.10.2026; millions of US dollars; Walmart's own fiscal-year names since v0.9.51):

| Walmart quarter | Q4 shown today (net sales, reported) | Q4 on the year's tag (year − nine months) | Where |
|---|---|---|---|
| FY2010Q4 (ends 2010-01-31) | 112,826 (10-K of 2011-03-30) | 113,622 = 408,085 − 294,463 (+0.7%) | latest, from 2011-03-30 on |
| FY2011Q4 (ends 2011-01-31) | 115,600 (10-K of 2012-03-27) | 116,360 (+0.7%) | latest and first-reported, from 2011-03-30 on |
| FY2012Q4 (ends 2012-01-31) | 122,285 (10-K of 2012-03-27) | 123,169 = 446,950 − 323,781 (+0.7%) | first-reported from 2012-03-27 on; latest only until 2013-03-26, when the next 10-K tags it under `Revenues` as 123,169 |

The net-sales figure is the same subtraction on net sales (405,132 − 292,306 = 112,826; 418,952 − 303,352 = 115,600; analyst), so the gap is the membership and other income, not a recast. First-reported FY2010Q4 is already a derivation (113,651, the 10-K of 2010-03-30 less the 10-Q of 2009-12-08) and does not move.

So a quarter series, a trailing year built from quarters, and any run dated from 2011-03-30 that holds these quarters in its history read three quarters of one line and a fourth of a narrower one, with nothing to say so.

Scan (every duration item, all eight companies, as of 2010-06-01, 2011-06-01, 2012-06-01, 2013-06-01, 2015-06-01, 2019-06-01, 2023-06-01 and 2026-11-09, latest with and without one basis, and first-reported; the analyst ran ten dates from 2010-06-01): a reported quarter whose tag ranks below the one tag its year and the periods before it share happens **only on these three Walmart revenue quarters**. No stored run (Walmart's start 2019-04-01; no Walmart assumption rows for 2010–2012) and no evaluation case (Walmart's from 2019-05-15) reads them, so no stored number moves.

This is not #297 item 13 (no figure was recast) nor a tag that changed meaning (`tag_meaning_changes` needs one tag to move). It is #295 item 1 seen from the other side: there, derived quarters mix tags; here, a reported quarter does.

## Plan

**Step 0. This doc.**

**Step 1. The rule** (`domains/fundamentals/facts.py`, `schemas.py`).

- In `_quarters_for_flow`, after the usual placement: a quarter (Q2, Q3 or Q4) that is reported, and shown as reported (not already replaced by a derivation; in first-reported mode a derivation public first already wins, `facts.py` `place`), is replaced by its derivation when every input of the derivation (Q4: year − nine months, else year − Q1 − Q2 − Q3; Q3: nine months − six months, else nine months − Q1 − Q2; Q2: six months − Q1; the same order the code already uses, `DERIVATIONS`; the first set whose periods are all reported is the one judged) is reported, all inputs, the minuend and every subtracted period, carry one tag, and that tag ranks above the quarter's own tag in the concept map for the item. In latest mode with `one_basis` the derivation goes through `_Basis.place` as any derived quarter does.
- The replaced quarter is a derived fact as any other (`derived`, `inputs`, `xbrl_concept` "Revenues − Revenues", `filed_at` its newest input) plus a new field `Fact.narrower_tag`: the tag of the reported quarter it replaces (`us-gaap:SalesRevenueNet`). None everywhere else.
- Applies in latest and first-reported mode (first-reported uses each input as first filed). Evaluation actuals are first-reported (Decision 7), so they follow the rule too; no case reads these quarters. Q1 has no derivation and is never replaced. The rule never makes a value from a tag the concept map does not list for the item, and never replaces a quarter whose inputs are themselves derived.
- Tests (`tests/fundamentals/test_quarterly.py`, Test Corp): a 10-K gives Q4 only under the item's third-ranked tag while the year and the nine months use the first: Q4 is the derivation, `narrower_tag` names the third tag, in both modes and with `one_basis`; Q4 under the same tag as the year is kept as reported; Q4 under a higher-ranked tag than the year is kept; inputs on two tags keep the reported quarter; a Q3 case works the same way; before the year is public no Q4 exists, as today; a later 10-K that gives the quarter under the year's tag makes it reported again from its filing date, while first-reported keeps the derivation (Walmart's FY2012Q4, analyst).
- Exit: full suite passes.

**Step 2. Say so** (`domains/analysis/reported.py`, `math_engine.trace`, `sources.filing`).

- The run trace adds "(worked out on the year's tag: its own filing gives the quarter only under {tag}, a tag ranked below it)".
- A source row gains `narrower_tag` (absent on rows stored before, which means None).
- `reported_period(conn, ticker, period, as_of).lines` and `prior_lines`: a line gains `tag_note`, a coded note `quarter_on_year_tag` with params `item`, `period`, `period_end` (ISO, so a student can find the quarter in the 10-K), `value`, `reported_value`, `reported_tag`, `tag`, `form`, `filed_at` (ISO) and `accession_no` (the filing that gave the narrower figure), and English text built from them: "revenue FY2010Q4 (the quarter ending 2010-01-31) is 113,622,000,000, worked out from figures all under us-gaap:Revenues, the tag of the year and the other quarters; the 10-K filed 2011-03-30 gives the quarter as 112,826,000,000, but only under us-gaap:SalesRevenueNet, a tag Warren ranks below it, so the four quarters would not measure the same line or add up to the year". "Ranks below", not "narrower": the engine trusts the concept map, it does not check the meaning (professor). The terminal (`reported` command) prints the note under the line. Ratios that use such a line get `uses_quarter_on_year_tag` (`items`, `periods`), as `uses_one_basis_line` does.
- Tests (`tests/analysis/test_reported.py`): the reported view of Test Corp's case carries the note with every param and the ratio note, `changed` stays false (product lead); a company without the case has no note; the trace and source row carry the tag.
- Exit: `python -m pytest -q` passes; `ruff check .` and `ruff format --check .` clean.

**Step 3. Real data** (snapshot of nov.10.2026). Exit: the scan finds only the three Walmart quarters above (anything else stops the merge and is studied); `python -m domains.analysis reproduce --all` reproduces every stored run.

## Step 3 results (nov.11.2026)

- Scan: only the three Walmart revenue quarters, values as in the table, in the modes and dates listed (the run of eight dates above; the analyst's ten-date run on the code agrees). All three also pass a value check the code does not make: the narrow tag's own year less nine months equals the reported narrow quarter (analyst).
- `reported --ticker WMT --period FY2011Q4 --as-of 2026-11-09`: revenue 116,360 with the note (10-K filed 2012-03-27, 115,600 under SalesRevenueNet); gross, operating, net margin, capex and D&A shares and growth carry `uses_quarter_on_year_tag`. FY2010Q4: 113,622 with the note (10-K filed 2011-03-30, 112,826); its `changed` flag was already true and stays so (first reported 113,651, the year recast by 0.01% in a later 10-K).
- Reproduce: `reproduce --all` on the built code, 903 of 903 runs reproduce to the cent. Full suite 2,113 passed, 10 skipped (Step 1); see the PR for the final count.

## Alternatives considered

- **A note only, values kept** (the issue's first option). The quarter would still be on the wrong line for every run and series, and Q1–Q4 would not add up to the year. A note explains an error the data lets us avoid.
- **Rank SalesRevenueNet above Revenues.** Wrong for Walmart's other periods and for every company that tags a contract-revenue subtotal (concept map note).
- **Re-derive only under `one_basis`** (as #290 did for `_paired_tag`). Leaves the reported view, first-reported actuals and the series on the mix; the bug is not about bases.
- **Also check the value** (analyst's suggestion 4: the narrow tag's own derivation must equal the reported quarter). It would catch a recast quarter filed only under a lower tag; none exists, and the three real cases pass it. Kept out because it needs every filing's lower-ranked tags for the year and nine months (`_tagged`), not only the best ones; listed in Limits and the follow-up issue.
- **Fix every mixed-tag derivation now** (#295 item 1). Larger (40 derived quarters across items mix two tags, mostly D&A at P&G and Walmart, many where the two tags mean the same), and changes run inputs; stays in #295.

## Decision 2

The professor and the analyst both read this as outside Decision 2 (no owner card): Decision 2 (`docs/structure-guide.md`, "Which version wins") ranks the versions of one period; the choice between a reported and a derived quarter is M1's normalisation (`docs/build-plan.md`, M1 notes). Decision 2 picks, for each period, the highest-ranked tag that reports it, then its newest filing. That rule is unchanged: it still picks `SalesRevenueNet` as the only version reported *for that quarter*. What changes is the quarterly view's choice between a reported quarter and a derived one (`_quarters_for_flow`, M1's "deriving the ones not reported"), which Decision 2 does not set: a derived quarter on the year's higher-ranked tag now beats a reported one on a lower-ranked tag, which is Decision 2's own reason for ranking tags first ("a later filing repeating the period under a broader or narrower measure" is definition drift, not a different figure). If a reviewer reads this as a change to Decision 2, it goes to the owner as a card and this stays on the branch.

## Files

`domains/fundamentals/facts.py`, `domains/fundamentals/schemas.py`, `domains/analysis/reported.py`, `domains/analysis/math_engine.py`, `domains/analysis/sources.py`, `domains/analysis/__main__.py` (terminal line), `tests/fundamentals/test_quarterly.py`, `tests/analysis/test_reported.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q1 and Q2 (a quarter's figures and a series of quarters): Walmart's quarters FY2010Q4 to FY2012Q4 now sit on the same line as the other quarters. In the latest view the four quarters of FY2010 still differ from the year by a little (408,113 against 408,085): Q1 is as first filed while Q2 and Q3 were recast, which is #264's and #297's ground, not this change (analyst).

- **Value change:** Walmart revenue FY2010Q4 (112,826 → 113,622) and FY2011Q4 (115,600 → 116,360) in every view; FY2012Q4 (122,285 → 123,169) as first reported, and in the latest view on dates from 2012-03-27 to 2013-03-26. Reported view, series and any run whose history holds them. No stored run or score reads them.
- **Added:** `Line.tag_note` (code `quarter_on_year_tag`, params in Step 2), ratio note `uses_quarter_on_year_tag` (`items`, `periods`), source field `narrower_tag`. Nothing renamed or removed.
- Note order (product lead): group 2 of the brief's "Notes on a reported figure", after `meaning_note` with `first_reported_differs` and before `sign_flip_skipped` and `basis_note`; on a ratio, `uses_quarter_on_year_tag` before `uses_sign_checked_line`, `uses_one_basis_line` and `uses_changed_line`. Suggested Spanish (product lead): "Ingresos del 4.º trimestre del ejercicio {año} (trimestre que termina el {period_end}): {value}, calculados como el año menos los primeros nueve meses, todo con la misma etiqueta XBRL ({tag}). El {form} presentado el {filed_at} da este trimestre como {reported_value}, pero solo con la etiqueta {reported_tag}, que Warren clasifica por debajo de la del año y los otros trimestres. Warren usa el cálculo para que los cuatro trimestres midan lo mismo. No es una corrección de cifras: son dos líneas distintas." Lines stay unnamed ("ventas netas") until #297 item 5 (brief line 77).

## Limits

- Only quarters whose inputs are all reported and share one tag. A quarter that also has derived inputs keeps the reported figure.
- The rule trusts the concept map's ranking; it does not check that the lower-ranked tag is narrower by value, nor that its own derivation equals the reported quarter (true for all three real cases). If the ranking changes, the scan in Step 3 is the check to rerun.

## Design review (nov.11.2026)

- **Analyst (NO-GO on the doc, GO on the method; all blockers fixed).** 1: the period ends in the table were a year late (FY2010 ends 2010-01-31). 2: first-reported FY2010Q4 does not move (113,651). 3: there are three quarters, not two (FY2012Q4 as first reported, and latest until 2013-03-26); the scan now covers eight dates and every mode. Taken: Decision 7's actuals named, the "add up" claim qualified, the re-tag test (`test_a_later_filing_on_the_years_tag_gives_the_quarter_back_as_reported`), filing links. Not taken: the value check (Alternatives).
- **Professor (GO).** Defensible: the integral view of interim periods (APB 28, ASC 270-10-45) and comparability (Concepts Statement 8) both want four quarters on one measure; year less nine months is standard practice. Decision 2 not touched. Taken: "ranks below", not "narrower", in the text; `period_end` in the params; the rule written into the build plan's M1 notes. Left for the app: plain labels for tags (#297 item 5).
- **Product lead (GO).** Taken: `filed_at` param, the note order, the Spanish, `changed` asserted false. Not taken: objection 1 (labels): Walmart's fiscal 2010 ended 2010-01-31, so FY2010Q4 is Walmart's own name; the doc's table had the wrong end dates, now fixed.
- **Explainer.** Answered above: the ranking's home (concept map), which inputs must share the tag (all), six months for "half", Q1 never replaced, units (millions), Step 3's exit criterion.
