# Backlog #282: the reported view says when a version was skipped for a flipped sign

Issue: https://github.com/sonderbot-ar/warren/issues/282 (`backlog`, `front-end`) · Branch `backlog-282-sign-flip-note` · Status: in progress (nov.10.2026).

## Problem

Since v0.9.47 (#280, `docs/designs/backlog-280-sign-check.md`), a filing's version of a period whose sign is flipped against another version of nearly the same size is skipped, so the reported view (`reported_period`, brief Q1 and Q2) can show a figure from an older filing than the newest. Walmart's income tax for the year ending Jan 2009 is 7,145 million from the FY2010 10-K, though the FY2011 10-K came later (it printed 7,133 and tagged −7,133). Three things go unexplained:

1. **"Latest" is no longer the newest filing.** The as-reported note says each ratio "uses the latest value known on the as-of date" (`reported.py`, `AS_REPORTED`), and the line names the older filing with no reason.
2. **The revised flag goes off.** `Line.changed` compares the value used with the first-filed one, both 7,145 now, so the FY2011 10-K's 12 million revision is not flagged.
3. **A corrected first version is flagged as changed for the wrong reason.** For Caterpillar's H1 and Q2 2009 cost of revenue the first version was the flipped one (−12,779, then 12,779): `changed` is true, which a student reads as a restatement, though only the tag's sign was wrong (professor, #280 review).

`facts.skipped_sign_flips` lists every skipped version with the one used, but `reported_period` doesn't call it, and neither the line nor the terminal output says anything.

## Plan

- **Step 0.** This design doc.
- **Step 1. A coded note on the line, and on the ratios that use it** (`domains/analysis/reported.py`, `domains/analysis/__main__.py`).
  - `reported_period` calls `skipped_sign_flips(conn, cik, names, as_of)` for the items its lines show, as it calls `newest_filing_disagreements`.
  - A `Line` (in `lines` and `prior_lines`) gains `sign_notes`: a list, empty when nothing was skipped, of `{code: "sign_flip_skipped", params, text}`, one per skipped filing whose version the line rests on. Params:
    - `item` (canonical name) and `period` (the line's label, `FYyyyy` or `FYyyyyQn`);
    - `input_start`, `input_end` (ISO; `input_start` null for a balance): the period of the version that was checked, the line's own, or for a derived quarter the input it was derived from (the year, for Walmart's Jan 2009 Q4);
    - `used`: `{accession_no, form, filed_at, value}`, the version used;
    - `skipped`: `{accession_no, form, filed_at, value}`, the version skipped;
    - `first_reported_skipped` (bool): the skipped version is the first one filed, so `changed` is true because a tagging error was corrected, not because the company restated (Caterpillar 2009).
    A line rests on a skipped version when the pair's item and period are the line's (a reported line or a balance), or, for a derived quarter, when the pair's period is in the same fiscal year, ends by the line's end, and its used filing is one of the derivation's inputs (so the quarter subtracted that version).
  - Each ratio that uses such a line says so, as #290 did for one basis: note `uses_sign_checked_line`, params `items`, `periods`; growth checks the prior year's line too.
  - `AS_REPORTED`'s English text gains a clause: "(a version filed with its sign flipped is skipped, and the line says so)". The code and params are unchanged.
  - Terminal: a line with a sign note gets `(a version filed with the opposite sign, <value> in <form> <accession> filed <date>, was skipped)`.
  - Tests (`tests/analysis/test_reported.py`, on Test Corp): (a) the newest 10-K flips FY2018 tax (Walmart's case): the FY2018 line uses the FY2018 10-K, `changed` false, one note with both filings and `first_reported_skipped` false; the derived FY2018Q4 tax line carries the note with `input_start`/`input_end` the year; the tax-rate ratio carries `uses_sign_checked_line`; (b) the first 10-K flips FY2018 tax (Caterpillar's case): the newer 10-K's value is used, `changed` true, `first_reported_skipped` true; (c) point in time: before the second version is filed nothing is skipped and the line has no note; (d) a line with no skipped version has `sign_notes == []`, and no ratio has the code; (e) the terminal and JSON show it.
  - Exit: tests pass, full suite, ruff and format green.
- **Step 2. Real data** (snapshot `warren-20261105T101750Z`). `reported_period` for every company, every fiscal year and quarter from FY2008 to the latest, as of 2026-11-09 and 2011-06-01, listing every line with a sign note; every one of the five versions `skipped_sign_flips` lists on 2026-11-09 shows on at least one line, and no line carries a note for a pair it doesn't rest on. `analysis reproduce --all` passes (no run reads `reported_period`, so nothing stored changes).
  - Exit: the notes match the #280 list exactly.

**Point in time.** `skipped_sign_flips` reads only versions public on the as-of date, so a note shows from the day the second version is filed, never earlier. **LLMs.** None. **Invariants.** No value, ratio or stored row changes; only notes are added.

## Alternatives considered

- **One note on the period, not on the line.** Rejected: the source panel shows each line with its filing, so the reason belongs beside the filing it explains, as `basis_note` (#290) does.
- **A `skipped` version on `Line` without a code.** Rejected: every note the app shows carries a code and params (design principle "no text hard-coded in logic").
- **Rename `restated` in `facts.py` for a corrected sign** (professor, #280). Rejected here: `Fact.restated` feeds `mixed_vintage`, #264's one-basis rule and the harness's first-reported comparisons; renaming it is a fundamentals change beyond this request. `first_reported_skipped` gives the app what it needs to not call Caterpillar's 2009 cost a restatement.
- **List skipped flips beside `disagreements`.** Rejected: disagreements are tag drift on purpose (#280 leaves a skipped flip out of `newest_filing_disagreements`); mixing them would teach the wrong reason.

## Files to change

`domains/analysis/reported.py`, `domains/analysis/__main__.py`, `tests/analysis/test_reported.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (none: backlog items have no row).

## Product impact

Serves brief Q1 and Q2 (what a company reported for a period, `docs/product/brief.md`): the source panel can say why a figure comes from an older filing than the newest, and that a changed figure was a tagging correction. Added, nothing renamed or removed:

- `lines[]` and `prior_lines[]`: `sign_notes` (list, usually empty) of `sign_flip_skipped` notes, params as above.
- Ratio note `uses_sign_checked_line` (`items`, `periods`).
- `as_reported_note.text` (English fallback only) gains a clause; its code and params don't change.

Suggested Spanish: "Una versión de esta cifra, presentada con el signo invertido ({skipped.form} del {skipped.filed_at}: {skipped.value}), se omitió; se usa la del {used.form} del {used.filed_at}. El estado financiero impreso tiene el signo correcto: el error estaba en la etiqueta XBRL." With `first_reported_skipped`: "La cifra cambió respecto de la primera publicada porque esa primera versión tenía el signo invertido en su etiqueta, no porque la empresa reexpresara sus resultados." Today the note shows only on Walmart's income tax for the years ending Jan 2009 (and its Q4), Jan 2010 (between 2011-03-30 and 2012-03-27) and Jan 2011, and Caterpillar's cost of revenue for H1 and Q2 2009 (Step 2 confirms).
