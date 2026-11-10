# Backlog #282: the reported view says when a version was skipped for a flipped sign

Issue: https://github.com/sonderbot-ar/warren/issues/282 (`backlog`, `front-end`) · Branch `backlog-282-sign-flip-note` · Status: built and reviewed (nov.10.2026).

## Problem

Since v0.9.47 (#280, `docs/designs/backlog-280-sign-check.md`), a filing's version of a period whose sign is flipped against another version of nearly the same size is skipped, so the reported view (`reported_period`, brief Q1 and Q2) can show a figure from an older filing than the newest. Walmart's income tax for the year ending Jan 2009 is 7,145 million from the FY2010 10-K, though the FY2011 10-K came later (it printed 7,133 and tagged −7,133). Three things go unexplained:

1. **"Latest" is no longer the newest filing.** The as-reported note says each ratio "uses the latest value known on the as-of date" (`reported.py`, `AS_REPORTED`), and the line names the older filing with no reason.
2. **The revised flag goes off.** `Line.changed` compares the value used with the first-filed one, both 7,145 now, so the FY2011 10-K's 12 million revision is not flagged.
3. **A corrected first version is flagged as changed for the wrong reason.** Walmart's year ending Jan 2011 was first tagged −7,579 (FY2011 10-K) and then 7,579: `changed` is true, which a student reads as a restatement, though only the tag's sign was wrong (professor, #280 review). Caterpillar's Q2 2009 cost of revenue was the same between its 10-Q/A (2010-08-26) and the 10-K that gave the quarter again (2011-02-22).

`facts.skipped_sign_flips` lists every skipped version with the one used, but `reported_period` doesn't call it, and neither the line nor the terminal output says anything.

## Plan

- **Step 0.** This design doc.
- **Step 1. A coded note on the line, and on the ratios that use it** (`domains/analysis/reported.py`, `domains/analysis/__main__.py`).
  - `reported_period` calls `skipped_sign_flips(conn, cik, names, as_of)` for the items its lines show, as it calls `newest_filing_disagreements`.
  - A `Line` (in `lines` and `prior_lines`) gains `sign_notes`: a list of `Coded` notes (`{code, params, text}` in JSON, as every other note), empty by default, one `sign_flip_skipped` per skipped filing whose version the line rests on. Params:
    - `item` (canonical name) and `period` (the line's label, `FYyyyy` or `FYyyyyQn`, as #279);
    - `input_start`, `input_end` (ISO; `input_start` null for a balance): the period of the version that was checked: the line's own, or for a derived quarter the input it was derived from (the year for a Q4 = year − nine months, the half or nine months for a Q2 or Q3);
    - `used`: `{accession_no, form, filed_at, value}`, the version used; `skipped`: the same for the version skipped. `value` is raw in the line's unit, with its sign as tagged; `filed_at` is ISO;
    - `first_reported_skipped` (bool): the skipped filing is the one the line's first-reported value came from (its filing, or one of its derivation's inputs), so `changed` is true because a tagging error was corrected;
    - `size_differs` (bool): the two sizes are not equal (within the 1% flip tolerance). Then part of the difference is a real revision (Walmart's Jan 2009 year: 7,145 used, the skipped 10-K tagged −7,133), and with `first_reported_skipped` the text does not say "not a restatement" (professor).
    A line rests on a skipped version (`reported._rests_on`) when `_in_scope` (the same rule as the disagreement rows) holds for the pair's used version: for a reported line, the same period (a balance by its end date); for a derived quarter, a period of the same fiscal year ending by the line's end, and the used filing is one of the derivation's input filings (`Version.inputs`, the minuend's filing included). A balance carried from an earlier date into net debt is not a line, so it gets no note; net debt's own notes name it.
  - Each ratio that uses such a line (by item name, as `uses_changed_line` and `uses_one_basis_line` do) says so: note `uses_sign_checked_line`, params `items`, `periods` (`FYyyyy[Qn]`); growth checks the prior year's line too.
  - `AS_REPORTED`'s English text, on every response, gains a clause: "(a version whose sign is flipped against another filing's version of the same period is skipped, and the line says so)". It names the condition, so a line with no note is not read as checked when it has only one version (analyst: Walmart's Jan 2011 year as of 2011-06-01, −7,579 and a −172% tax rate, one version only; that is #283). The code and params are unchanged.
  - Terminal: a line with a sign note gets `(a version filed with the opposite sign, <value> in <form> <accession> filed <date>, was skipped)`; the full text is in the JSON.
  - Tests (`tests/analysis/test_reported.py`, on Test Corp, whose tax is 25% of pretax, positive; the FY2018 10-K, filed 2019-02-15, and the FY2019 10-K, filed 2020-02-15, both give the 2018 year): (a) the newest 10-K flips FY2018 tax (Walmart's case): the FY2018 line uses the FY2018 10-K, `changed` false, one note with both filings and `first_reported_skipped` false; the derived FY2018Q4 tax line carries the note with `input_start`/`input_end` the year; the tax-rate ratio carries `uses_sign_checked_line`; (b) the first 10-K flips FY2018 tax (Caterpillar's case): the newer 10-K's value is used, `changed` true, `first_reported_skipped` true; (c) point in time: before the second version is filed nothing is skipped and the line has no note; (d) a line with no skipped version has `sign_notes == []`, and no ratio that doesn't use it has the code; (e) the terminal and JSON show it; (f) a corrected first version 0.5% off in size has `size_differs` and its text does not say "not a restatement".
  - Exit: tests pass, full suite, ruff and format green.
- **Step 2. Real data** (snapshot `warren-20261105T101750Z`). `reported_period` for every company, every fiscal year and quarter from FY2007 to FY2026, as of 2026-11-09, 2011-06-01 and 2010-09-01, listing every line with a sign note; `analysis reproduce --all`.
  - Exit: a note on every line that rests on a skipped version, and on no other (analyst: the first exit, "every one of the five versions shows on a line", could not be met, since a half-year is never a line and Caterpillar's Q2 2009 line now rests on the 10-K, not the corrected 10-Q).

## Results (nov.10.2026)

Over 8 companies × 20 fiscal years × 5 periods on three dates, only Walmart's income tax and, on 2010-09-01, Caterpillar's cost of revenue carry a note (values in millions):

| As of | Line | Used (filing) | Skipped (FY2011 10-K, 0001193125-11-083157, unless said) | `first_reported_skipped` | `size_differs` | `changed` |
|---|---|---|---|---|---|---|
| 2026-11-09 and 2011-06-01 | WMT FY2008 (year ending Jan 2009) and its Q4 (1,959) | 7,145 (FY2010 10-K) | −7,133 | false | true | false |
| 2026-11-09 | WMT FY2009 and its Q4 (1,999) | 7,156 (FY2012 10-K) | −7,156 | false | false | true (7,139 first) |
| 2011-06-01 | WMT FY2009 and its Q4 (1,925, one basis) | 7,139 (FY2010 10-K) | −7,156 | false | true | false |
| 2026-11-09 | WMT FY2010 and its Q4 (2,294) | 7,579 (FY2013 10-K) | −7,579 | true | false | true |
| 2010-09-01 | CAT FY2009Q2 cost of revenue | 5,752 (10-Q/A, 2010-08-26) | −5,752 (10-Q 0000018230-09-000331) | true | false | true |

So the Jan 2010 note shows from 2011-03-30 on, not only until 2012-03-27 (explainer, analyst): the flipped version stays skipped after the FY2012 10-K. Caterpillar's note shows only between 2010-08-26 and 2011-02-22: after that its Q2 2009 line is read from the 2011 10-K's quarter (2009-03-31 to 2009-06-30), which rests on no flipped version, and its H1 is never a line. Every derived Q4 above lists the used filing among its inputs, with and without one basis (analyst), and no line rests on a pair of another fiscal year (WMT FY2011Q4 also uses 0001193125-12-134679 and correctly gets no note). Every line with a note sits under an `effective_tax_rate` (or, for CAT, a `gross_margin`) with `uses_sign_checked_line`. `python -m domains.analysis reproduce --all` on the branch: 903 of 903 runs reproduce to the cent (no run reads `reported_period`).

**Point in time.** `skipped_sign_flips` reads only versions public on the as-of date, so a note shows from the day the second version is filed, never earlier. **LLMs.** None. **Invariants.** No value, ratio or stored row changes; only notes are added.

## Alternatives considered

- **One note on the period, not on the line.** Rejected: the source panel shows each line with its filing, so the reason belongs beside the filing it explains, as `basis_note` (#290) does.
- **A `skipped` version on `Line` without a code.** Rejected: every note the app shows carries a code and params (design principle "no text hard-coded in logic").
- **Rename `restated` in `facts.py` for a corrected sign** (professor, #280). Rejected here: `Fact.restated` feeds `mixed_vintage`, #264's one-basis rule and the harness's first-reported comparisons; renaming it is a fundamentals change beyond this request. `first_reported_skipped` gives the app what it needs to not call Caterpillar's 2009 cost a restatement.
- **List skipped flips beside `disagreements`.** Rejected: disagreements are tag drift on purpose (#280 leaves a skipped flip out of `newest_filing_disagreements`); mixing them would teach the wrong reason.

## Files to change

`domains/analysis/reported.py`, `domains/analysis/__main__.py`, `tests/analysis/test_reported.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (none: backlog items have no row).

## Limits

- **A lone wrong version is not caught**, so it has no note: Walmart's year ending Jan 2011 as of 2011-06-01 reads −7,579 (tax rate −172%) until the FY2012 10-K. That is #283 (flag a lone version against a strong usual sign).
- **The skip loses a small revision** (Walmart's Jan 2009 year: 7,145 used, though the FY2011 10-K's tagged size is 7,133). Correcting the sign instead was rejected in #280 for provenance (no stored fact holds +7,133); `size_differs` lets the app say a newer filing gives a slightly different size.
- **Matching by input filing.** If a one-basis derivation ever took its minuend from an older filing than the pair's used one (`facts._Basis.place`), the quarter would not rest on that pair and gets no note, which is right; but a version skipped in that older filing's own set would need its own pair. Not seen on the eight companies (analyst).
- **What the engine knows.** It sees two versions of opposite sign and nearly the same size, and uses the one the period's other versions, or the company's other periods, agree with. It does not read the printed statement, so no field or text says the printed statement was right (product lead, professor): that is checked for Walmart's FY2011 10-K only (#280).

## Product impact

Serves brief Q1 and Q2 (what a company reported for a period, `docs/product/brief.md`): the source panel can say why a figure comes from an older filing than the newest, and that a changed figure was a tagging correction. Added, nothing renamed or removed:

- `lines[]` and `prior_lines[]`: `sign_notes` (list, usually empty) of `sign_flip_skipped` notes, params as above.
- Ratio note `uses_sign_checked_line` (`items`, `periods`).
- `as_reported_note.text` (English fallback only) gains a clause; its code and params don't change.

How to show it (product lead review): put the sign note before `uses_changed_line` on the line and in the ratio, since it explains the change; write `value` in millones de US$ like the statement and `filed_at` as "presentado el 30 mar 2011"; show the skipped value with its sign as tagged, labelled "valor etiquetado", and gloss the tag once ("la etiqueta XBRL es la copia legible por máquina del estado financiero, no el estado mismo"). Suggested Spanish: "Una versión de esta cifra se omitió: el {skipped.form} presentado el {skipped.filed_at} la etiquetó con el signo opuesto ({skipped.value}, valor etiquetado), casi del mismo tamaño que la del {used.form} presentado el {used.filed_at}. Se usa la versión que coincide con las demás presentaciones." With `size_differs`: add "El tamaño también difiere un poco, así que parte de la diferencia es una revisión." With `first_reported_skipped` and not `size_differs`: "La cifra cambió respecto de la primera publicada porque esa primera versión tenía el signo invertido en su etiqueta, no porque la empresa cambiara la cifra." (no "reexpresar": the #279 and #290 rule; under NIC 8 it means correcting an error, and in Argentina it reads as NIC 29.) Today the note shows only on Walmart's income tax for the years ending Jan 2009, Jan 2010 and Jan 2011 and their fourth quarters (from 2011-03-30 for the first two, from 2012-03-27 for the third), and on Caterpillar's Q2 2009 cost of revenue between 2010-08-26 and 2011-02-22 (Results).

## Design review (nov.10.2026)

Explainer, analyst, professor and product lead, as fresh-context subagents, on the first draft.

- **Analyst: NO-GO on the doc, method sound; both blockers taken.** (1) Caterpillar's H1 is never a line and its Q2 2009 line rests on the 2011 10-K from 2011-02-22, so the first Step 2 exit could not be met: exit reworded, Caterpillar's window stated. (2) The Jan 2010 window ("until 2012-03-27") was wrong and `size_differs` was missing from the param list: both fixed. Ideas taken: the as-reported clause names its condition (a lone version is not checked, #283); the matching limit listed. Idea not taken: correcting the sign instead of skipping (rejected in #280 for provenance; Limits).
- **Professor: approve, no blockers.** Sources: Du, Vasarhelyi & Zheng (2013, *JIS*) and Debreceny et al. (2010, *JAPP*) on sign errors; XBRL US DQC_0015; SEC Release 33-9002 (the HTML statement was authoritative in 2009–2011); ASC 250-10-20 for "restatement". Taken: "not a restatement" only when the sizes match (`size_differs`, test (f)); the claim that the printed statement is right is not asserted by the engine (Limits); the XBRL gloss and "presentado en el 10-K" in the Spanish.
- **Product lead: GO on the fields, two Spanish blockers taken.** "Reexpresara" replaced; the printed-statement sentence dropped (the engine never reads it). Ideas taken: `size_differs`, which note first, formats, "valor etiquetado".
- **Explainer: gaps, taken.** The window, the input field (`Version.inputs`, minuend included), `_in_scope` reuse and balances, input periods for Q2 and Q3, a carried balance, how ratios match and the periods' format, the clause on every response, the type (`Coded`, default empty), what "first" means, the fixture's years, the five pairs listed in Results.

