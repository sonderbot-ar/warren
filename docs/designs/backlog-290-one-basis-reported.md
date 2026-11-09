# Backlog #290: the reported view shows a quarter on one basis, as a run reads it

Issue: https://github.com/sonderbot-ar/warren/issues/290 · Branch `backlog-290-one-basis-reported` · Status: built, in review (nov.09.2026).

## Problem

A run reads a derived quarter on one basis (backlog #264): when part of a year was recast, Q4 is not the old year less the recast nine months (a number on no basis) but a pair that shares one. The reported view (`reported_period`, brief Q1 and Q2) still showed the plain derivation, so the two disagreed on the same quarter and the same date: JNJ FY2022Q4 revenue as of 2023-11-01 was 34,892 million in the reported view and 23,706 in a run. The front-end team chose option (b) in the #279 review: the engine returns the one-basis figure as the main number, the plain derivation beside it, and a code saying which is which.

The gatekeeper on #278 asked for a spot-check first: `one_basis` also changes quarters no run reads (items like pretax income or D&A of years outside any run's window), and nobody had looked at them.

## Plan

**Step 0. The spot-check, and the one wrong quarter it found.** Every item-quarter where `get_facts(one_basis=True)` differs from the plain derivation, for every company, on the 136 stored run dates plus 2023-11-01 and 2026-11-09 (138 dates). Result: 74 item-quarters across all 8 companies (table below). Each was checked against the other quarters of its year and the same quarter a year before and after, and the large ones against the figures the companies published at the time.

- 73 are the quarter as the company reported it at the time (69 rows, `first_filed`) or on the later basis throughout (4 rows, #264 rule 2). Where the gap is large, the plain derivation is the broken one: JNJ FY2021Q4 revenue 9,769 plain against 24,804 one basis (24,804 is what JNJ reported for Q4 2021); MSFT FY2016Q4 pretax income 9,235 against 3,347 (3,347 less tax 225 is the 3,122 net income Microsoft reported); CAT FY2014Q4 pretax −991 against 940 (Caterpillar reported a profit; the loss is the 2016 pension accounting change applied to the year only); PG FY2013Q4 cost of sales 8,417 against 10,854 (47% gross margin, as reported, against 59%). Where the gap is small (WMT, under 0.2%), both are plausible and the one-basis figure is the consistent one.
- **1 was wrong: AAPL FY2017Q4 D&A, 527 million on one basis against 2,484 plain** (Apple's Q4 is about a quarter of its 10,157 year). Not a recast but a change of tag: Apple's 2017 10-K gives the year under the cash-flow tag the 10-Qs use (10,157) and under a higher-ranked tag holding depreciation alone (8,200); later 10-Ks put 10,157 under the higher tag. #264 compared each filing's best tag, so it read the 2017 10-K as an older basis (8,200) and paired it with the nine months (7,673). This is the "pairing across tags" gap in #264's Limits.
- **Fix:** when the subtracted periods share one tag, `_Basis` reads each filing's version of the year under that tag where the filing gives it (`facts._tagged`, `_Basis._paired_tag`). The re-run changes exactly that row (73 rows left, the other 72 identical, none added); AAPL FY2017Q4 D&A goes back to the plain 2,484. AAPL FY2015Q4 D&A stays 3,119 (the fix keeps it: the year under the 10-Qs' tag is 11,257; the plain 1,062 is the mixed-tag one).
- No stored run reads AAPL D&A for FY2017Q4 (`assumptions`, `history:d_and_a`); `python -m domains.analysis reproduce --all` passes on the real database.
- Test: `test_one_basis_reads_a_filing_under_the_nine_months_tag` (fails before the fix with 70, passes with 130).

Exit: every row checked; the one wrong row fixed at its source, with a test.

| Company | Rows | Items | One basis is |
|---|---|---|---|
| AAPL | 1 (was 2) | D&A FY2015Q4 | right (3,119; plain 1,062 mixes tags) |
| CAT | 9 | capex FY2008Q4, FY2010Q4; FY2014Q4 tax, net income, operating expenses, operating income, pretax; FY2016Q4 operating expenses and income | first filed, before the 2016 pension change was applied to the years only |
| JNJ | 13 | FY2013–14 amortisation, FY2016Q4 cost; FY2021Q4 and FY2022Q4 revenue, cost, pretax, tax, amortisation | as reported (FY2021Q4 revenue 24,804; FY2022Q4 23,706) until the Kenvue recast gives the year |
| KO | 23 | FY2010Q4, FY2016–19 several items | as reported (FY2017Q4 revenue 7,512; FY2018Q4 7,058); 2 rows rule 2 |
| MSFT | 4 | FY2013Q4 cost and operating expenses; FY2016Q4 tax and pretax | as reported (pretax 3,347) |
| PG | 10 | FY2010–18 cost of sales and tax | as reported; 2 rows rule 2 |
| WMT | 11 | FY2008Q4, FY2011Q4, FY2012Q3 | first filed; under 0.2% from plain |
| XOM | 2 | FY2017Q4, FY2018Q4 revenue | first filed (65,312; 68,253) |

The scan: for each company and date, `get_facts(conn, cik, names, d, frequency="quarterly", one_basis=True)` against the same call without `one_basis`, keeping facts with `one_basis` whose value differs.

**Step 1. The reported view on one basis.** In `reported_period` for a quarter, lines come from `get_facts(..., one_basis=True)`, the facts a run reads; the plain derivation is read beside it. A `Line` gains:

- `one_basis` (bool): the value was put on one basis and differs from the plain derivation;
- `plain` (`Version` or null): the plain derivation, with the filings it came from;
- `basis_note` (`{code: "one_basis", params, text}` or null): params `item`, `period` (`FYyyyyQn`), `value`, `plain_value`, `basis` (`first_filed`: the quarter as first reported, because no filing gives the whole year on the new basis yet; `restated`: the first filing that gives the year on the new basis, #264 rule 2).

`value`, `latest`, `first_reported` and `changed` keep their meaning: `value` is still the latest known on the as-of date, now on one basis, so it is the figure a run reads. Ratios use it (they read the same facts), and every ratio that uses such a line says so: note `uses_one_basis_line`, params `items`, `periods`; growth checks the prior year's quarter too. A year, a balance and a quarter reported on its own are never put on one basis. The terminal shows "(on one basis; plain derivation …)" beside the line.

Tests (`tests/analysis/test_reported.py`): on the #264 fixture as of 2019-12-31, FY2018Q4 revenue is the year less the quarters as first reported, `plain` holds the old year less the recast quarters, `basis_note` carries its params, the run's `history:revenue` for the same quarter and date is the same number, the operating margin and growth carry `uses_one_basis_line`, and an item not recast has no plain value; a reported quarter and a year are never put on one basis; the terminal text and the JSON show it. Real data: for every revenue row of the scan, on its first and last date where a run can be built, the reported view and `build_inputs` give the same number (9 of 9; dates where prices are older than the date skipped).

Exit: the reported view and a run agree on every quarter they both show.

## Alternatives considered

- **Keep `value` plain and add the one-basis figure beside it.** Rejected: the product lead chose the one-basis figure as the main number so brief Q1 agrees with a run; ratios computed on the plain figure would disagree with the line the screen shows.
- **A `basis` field on every line (`math_engine.basis_kind`).** Tried and dropped: on a reported quarter first given alone in a later 10-K (JNJ FY2022Q4 as of 2026: 19,939 on the new basis, `changed` true) it says `unchanged`, which a reader would take as "not recast". `changed` and `basis_note` already say what the screen needs; the kind stays in `basis_note.params`.
- **Fix the tag pairing for every derivation, not only on one basis.** Rejected here: the plain and first-reported derivations would change for rows runs read (AAPL FY2015Q4's plain is mixed-tag), a change to the M1 rule ("best tag first") that needs its own review. Listed under Limits.
- **Skip `one_basis` in the reported view for rows the spot-check could not confirm.** Rejected: every row but one was confirmed, and the one was fixed at its source.

## Files

`domains/fundamentals/facts.py` (`_tagged`, `_Basis._paired_tag`), `domains/analysis/reported.py` (`Line.one_basis`, `plain`, `basis_note`; `_views`, `_basis_note`, `_one_basis_note`), `domains/analysis/__main__.py` (terminal), `tests/fundamentals/test_quarterly.py`, `tests/analysis/test_reported.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q1 and Q2 (`docs/product/brief.md`). For a quarter, each line in `reported_period(...).lines` and `prior_lines` gains three fields, nothing renamed or removed:

- `one_basis`: true when the figure was put on one basis; the screen shows `value` as the main number.
- `plain`: the plain derivation (`value`, `xbrl_concept`, `filed_at`, `filing` null, `inputs` with each filing's form, accession, date and EDGAR link), for the side panel; null otherwise.
- `basis_note`: `{code: "one_basis", params: {item, period, value, plain_value, basis}, text}`; `basis` is `first_filed` or `restated`. `item` is a canonical name; the ones the scan shows are `revenue`, `cost_of_revenue`, `operating_expenses`, `operating_income`, `pretax_income`, `income_tax_expense`, `net_income`, `net_income_including_nci`, `interest_expense`, `depreciation_amortization`, `amortization_intangibles`, `capex` and `discontinued_operations`, and any duration item in the concept map can occur. `period` is `FYyyyyQn`, which the app writes as "4.º trimestre del ejercicio 2022" (#279); `value` and `plain_value` are raw amounts in the line's `unit`, which the app formats in millones de US$ (design principles). Suggested Spanish, following #279's wording rule (no "reexpresado": under NIC 8 it means correcting an error, and in Argentina it reads as NIC 29): "Este trimestre se calcula con cifras sobre una misma base contable (el mismo criterio de presentación para todas las cifras): {item} del {period} es {value}, no {plain_value} (el año menos los otros trimestres, cada uno en su versión más reciente), porque una presentación nueva cambió las cifras de parte del año (reclasificadas o ajustadas por la empresa)." Then, for `first_filed`: "Ninguna presentación da aún el año completo en la nueva base, así que se usan las cifras de la presentación original." For `restated`: "Se usa la primera presentación que da el año completo en la nueva base."
- On a `first_filed` line `changed` can be false while `one_basis` is true; the side panel shows the `one_basis` reason first, then first reported against latest when `changed`.

Ratios gain the note `uses_one_basis_line` (`items`, `periods`). Values change for the 73 item-quarters in the table, on the dates in the scan (most of them on every date; JNJ FY2022Q4 between 2023-11-01 and 2024-02-15). JNJ FY2022Q1–Q2 as of 2023-11-01 are reported quarters not yet refiled: no flag, `changed` false, nothing implies they are on the new basis.

Effect on runs: none for stored runs (reproduce passes); a new run of AAPL whose window reads FY2017Q4 D&A gets 2,484 instead of 527.

## Limits

- **Tags beyond one basis.** The plain and first-reported derivations still read each filing's best tag: AAPL FY2015Q4 D&A plain is 1,062 (mixed tags) and FY2017Q4's first-reported derivation is 527. A follow-up issue covers the best-tag rule for derivations.
- **Several tags in the subtracted periods.** When Q1–Q3 or the nine months use more than one tag, the year is read under the best tag as before.
- **A shared tag is necessary, not sufficient, for a shared basis.** The tag fix removes one false signal (a filing's tag switch read as a recast); a company can recast under the same tag, which the #264 rules already handle.
- **A filing without the paired tag** is read under its best tag, as before (`_Basis._paired_tag`), so a mixed-tag pairing can remain for that filing; none occurs in the scan. `_vintage` still reads each filing's best tag to date the subtracted periods (analyst); no scan row depends on it. Both go to the follow-up issue.
- **A tag that changes meaning.** XOM's `Revenues` moved from sales to total revenues and other income in the 2020 10-K, so FY2018Q4 growth as of today (+10.1%) compares total revenue with the prior year's sales (65,312, one basis); like for like on sales it is about +4.5%. Runs read the same numbers and it predates this item (before it, −0.9% against a mixed-tag 72,513); the note `uses_one_basis_line` doesn't say it. Follow-up issue.
- The spot-check covers the stored run dates and two more; a date between them can only show a row that appears and disappears between two scanned dates.

## Design review

- **Analyst: GO, no blockers.** Re-ran the scan with the fix and with it stubbed out: exactly one row changes (AAPL FY2017Q4 D&A, 527 to 2,484); 73 rows match the table. Spot-checks against what the companies reported: JNJ FY2022Q4 (revenue 23,706, pretax 4,201, tax 681), KO FY2018Q4 (7,058), MSFT FY2016Q4 (3,347 − 225 = the 3,122 net income), CAT FY2014Q4 (pretax 940, net 763 with the 757 to the parent), XOM FY2017Q4 (65,312). `build_inputs` and the reported view agree (JNJ, KO). Ideas taken into Limits: XOM's revenue tag changing meaning; `_vintage` on the best tag. Both in the follow-up issue.
- **Professor: GO, no blockers.** Recast vs as first reported follows ASC 250 / IAS 8 retrospective application and the Compustat point-in-time vs restated split; tag variation across filings for the same number is documented (Debreceny et al. 2010, *JAPP* 29; Chychyla & Kogan 2015, *JIS* 29(1)). Ideas taken: "a shared tag is necessary, not sufficient" and the paired-tag fallback in Limits; the Spanish avoids "reexpresó". Ideas left to the follow-up: name the filing in the `restated` note; a glossary line mapping "one basis" to "comparable basis".
- **Product lead: NO-GO on the doc, GO on the code; blocker taken.** The suggested Spanish used "reexpresó", which #279 had dropped (NIC 8 error correction; NIC 29 in Argentina): rewritten with "presentación nueva / original" and the gloss for "base contable". Ideas taken: a `restated` sentence, the list of items, the period and unit formatting, which the side panel shows first. At merge the front-end team updates brief Q1's "Hoy" line.
