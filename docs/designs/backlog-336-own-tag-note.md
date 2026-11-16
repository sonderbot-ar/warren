# Backlog #336: say when a quarter is kept on its own tag, and a sturdier own-tag check

Issue: https://github.com/sonderbot-ar/warren/issues/336 · Branch `backlog-336-own-tag-note` · Status: merged as v0.9.59 (PR #339, merge `cf95df2`, nov.12.2026).

From the review of #329 (PR #335, `docs/designs/backlog-329-quarter-tag-check.md`, Limits).

## Problem

Since v0.9.55 (#324) a quarter its filing gave only under a tag ranked below its year's (Walmart's fourth quarters as net sales, the year and the 10-Qs as total revenues) is worked out on the year's tag instead. Since v0.9.58 (#329) that move happens only if the same subtraction on the quarter's own tag gives the quarter back (within `RECAST_MOVE`, 0.5%). Two gaps were left, and one choice was to be revisited:

1. **A failed check says nothing** (analyst, professor). The quarter stays as filed on its own tag, with no `tag_note`: the four quarters then measure two lines again, as before #324, and neither the reported view, the run's trace nor the quality report says so.
2. **Inputs from different years' filings** (analyst). In latest mode each input is its newest version, so the check can read the year from a later 10-K: Walmart's FY2010Q4 takes the year from the 10-K of 2012-03-27 and the nine months from the 10-Q of 2009-12-08, while the quarter comes from the 10-K of 2011-03-30. If the later 10-K recast the narrow year, the check would fail although the quarter is right.
3. **The tolerance** (professor): a tolerance from the XBRL `decimals` attribute (DQC_0084) instead of `RECAST_MOVE`, to revisit once 1 and 2 are done.

## Plan

**Step 0. This doc.**

**Step 1. The check says what failed, and tries the quarter's own filing too** (`domains/fundamentals/facts.py`, `domains/fundamentals/schemas.py`).

- New model `OwnTagCheck` (`year_tag`, `on_year_tag`: the quarter on the year's tag, `on_own_tag`: the same subtraction on the quarter's own tag, `inputs`: the accessions of those own-tag inputs, minuend first, `minuend`: `FY`, `M9` or `H1`, and `on_own_filing`: the second pairing's figure when it differs from the first, else None; the last two from the analyst's review) and a field `Fact.kept_on_own_tag: OwnTagCheck | None`. `_on_year_tag` returns a small `_YearTag` (minuend, subtracted, `kept`); when `kept` is set, `_quarters_for_flow` keeps the reported quarter and copies `kept` onto it. Nothing else about the quarter changes (same value, tag, filing).
- `_own_tag_check` tries two pairings. First, as in #329, each input read from the filing that gave it. If that fails, second, each input the quarter's own filing also gives under the quarter's tag is read from there instead (the others still from their own filings): in the quarter's own filing the quarter and its year sit side by side, on one basis. The check passes if either pairing agrees. If an input's own filing lacks the quarter's tag there is still no check, as before. `OwnTagCheck` reports the first pairing (the inputs the derivation would have used).
- This is the issue's "compare the narrow year in the quarter's own 10-K with the narrow year in the year input's filing": when the two agree, the second pairing equals the first; it only differs when the narrow year was recast between them, which is exactly the case to rescue.
- Tests (`tests/fundamentals/test_quarterly.py`): the existing disagreement test now also asserts `kept_on_own_tag` (130 on the year's tag, 140 on the own tag, inputs 10-K and Q3 10-Q) in latest, first-reported and one-basis modes; no `kept_on_own_tag` when the quarter moves or is not checked; a later 10-K (where latest mode reads the year) recasts the narrow year to 470: the first pairing fails (145), the quarter's own 10-K gives 450 (125), so the quarter moves (this test fails without the second pairing); with the narrow year only in the later 10-K the quarter is kept and says 145 from the later 10-K; both pairings failing keeps it.
- Exit: full suite passes; the real-data scan below changes nothing.

**Step 2. Say it on the line, in the ratios, the trace and the quality report** (`domains/analysis/reported.py`, `domains/analysis/math_engine.py`, `domains/fundamentals/quality.py`).

- `Line.tag_note` gets a second code, `quarter_kept_on_own_tag`, params `item`, `period`, `period_end`, `value` (the quarter as filed), `own_tag` (its own tag; named so because `tag` in `quarter_on_year_tag` is the year's tag, product lead), `year_tag`, `on_year_tag`, `on_own_tag`, `own_tag_inputs`, `minuend`, `on_own_filing`, `form`, `filed_at`, `accession_no` (the quarter's own filing). English, in three sentences (professor): "revenue FY2010Q4 (the quarter ending 2010-01-31) is 112,826, as the 10-K filed 2011-03-30 gives it under us-gaap:SalesRevenueNet. The year and the other quarters use us-gaap:Revenues, a tag Warren ranks above it, but on us-gaap:SalesRevenueNet the year less the earlier periods is … (… with the figures in the quarter's own filing, when that differs), not 112,826, so Warren keeps the quarter as filed. The four quarters therefore measure two lines and may not add up to the year; on us-gaap:Revenues this quarter would be …." For a Q3 or Q2 it says "the nine months" or "the six months". The note does not say which figure moved: a failed check means the quarter or an input was revised on its own tag, and the check cannot tell which (analyst); the two figures let a reader see it.
- A ratio that uses such a line gets `uses_quarter_kept_on_own_tag` (`items`, `periods`); `uses_quarter_on_year_tag` is now given only for lines with that code.
- `math_engine.trace` (the run's evidence line) adds "(kept as filed under a tag ranked below the year's Revenues: on its own tag the year less the earlier periods is …)".
- The quality report gains a section, "Quarters kept on a lower-ranked tag", one row per quarter with both figures and the inputs' accessions ("None." otherwise), and `QualityReport.kept_on_own_tag`.
- Tests: `tests/analysis/test_reported.py` (the note's params and text, the ratio note on operating margin and growth, the trace; a quarter that agrees keeps `quarter_on_year_tag`); `tests/fundamentals/test_quality.py` (the section lists the quarter, and says "None." without one).
- Exit: full suite passes; `reproduce --all` 903 of 903.

**Item 3, the tolerance: kept as `RECAST_MOVE`.** Revisited, as the issue asked. A `decimals`-based tolerance needs each fact's `decimals`. Every fact in a filing's XBRL carries it; the limit is Warren's source: SEC's companyfacts API, Warren's only fundamentals source (Decision 2), does not carry that attribute (each row has `val`, `accn`, `fy`, `fp`, `form`, `filed`, `frame`); getting it means reading every filing's XBRL instance, a new adapter and a re-ingest, for a check that has never failed on real data. The reasons in #329's Alternatives still hold. If a filing-instance adapter arrives (the IFRS adapter in #314 may need one), this is worth another look.

## Real-data scan

Snapshot of nov.10.2026 restored (schema 22). Every item in the concept map, all eight companies, as of 2010-06-01, 2011-06-01, 2012-06-01, 2013-06-01, 2015-06-01, 2019-06-01, 2023-06-01 and 2026-11-09, latest with and without one basis and first-reported (106,822 quarter-views), this branch against `main`: **0 differences** in value, tag or `narrower_tag`; 43 quarter-views carry `narrower_tag` on both; **0 carry `kept_on_own_tag`**. The first pairing never fails on real data, so the second never decides. For Walmart's FY2010 the quarter's own 10-K (2011-03-30) and the later 10-K (2012-03-27) both give the net-sales year as 405,132 (the 10-K of 2010-03-30 had 405,046, 0.02% lower), so either pairing gives 112,826. `python -m domains.analysis reproduce --all`: 903 of 903 runs reproduce to the cent.

## Alternatives considered

- **Only the quarter's own filing** (drop the first pairing). Fails more often: a 10-K's quarterly note seldom repeats the nine months, so a fourth quarter would rarely be checkable.
- **Swap anyway when the second pairing alone agrees, but flag it.** That is what the two pairings do, minus the flag; a flag on a quarter that agrees on its own filing would tell the student nothing they can act on.
- **A note on the year's figure instead of the quarter.** The quarter is the line that differs; the year is reported on its usual tag.
- **Store `kept_on_own_tag` in the run's sources** (`sources.filing`). Left out: the source rows are compared on rebuild, a new key would need the same "absent means None" care as `narrower_tag`, and no stored run reads such a quarter. The trace line says it.

## Limits

- Constructed cases only: no real quarter is kept today.
- The second pairing reads only the inputs the quarter's own filing gives; a nine months recast between its 10-Q and a later one is still read from its own 10-Q, as before.

## Design review (nov.12.2026)

Analyst, professor and the product lead in parallel, on the built branch (as for #329; the explainer was not run).

- **Analyst: GO.** Re-ran a scan on four dates (41,161 quarter-views, 15 moved, every check passing on the first pairing). The second pairing cannot let a revised quarter move: a 10-K that restated Q1–Q3 still pairs with the original nine months. Ideas, all **taken**: (1) say "the six months", "the nine months" or "the year" to match the minuend, in the note, the trace and the quality report (`OwnTagCheck.minuend`, `MINUEND_WORDS`; test for a kept Q3); (2) the note claimed the quarter "was revised on its own tag", a cause the check cannot prove (an input may have moved): reworded to "…is …, not …, so Warren keeps the quarter as filed"; (3) show the own-filing figure too when both pairings fail (`on_own_filing`; the test with both failing now shows 145 and 115). No objection to the mixed filing dates of a rescued quarter (flagged as before through `mixed_vintage`) or to `RECAST_MOVE`.
- **Professor: GO.** The check is the calculation-consistency idea behind DQC_0084; reading the quarter and its year from one filing fits ASC 250 (a recast restates every period a filing shows). Confirmed SEC's API page lists no `decimals` for companyfacts rows. Suggestions **taken**: split the English note into three sentences; say the limit is the source, not XBRL (Item 3). Lesson idea: S-K Item 302(a) since Release 33-10890.
- **Product lead: GO.** Nothing the app relies on breaks; the filing link is always present. **Taken:** `tag` meant the year's tag in `quarter_on_year_tag` and the quarter's own tag here, so the param is `own_tag`. Placement: group 2 of "Notes on a reported figure", the slot the brief reserves for #336; the ratio note where `uses_quarter_on_year_tag` goes. Spanish (with `minuend` read as "el año", "los nueve meses" or "los seis meses"): "Ingresos del {trimestre} trimestre del ejercicio {año} (trimestre que termina el {period_end}): {value}, tal como los da el {form} presentado el {filed_at}, con la etiqueta XBRL {own_tag}. El año y los otros trimestres usan otra etiqueta ({year_tag}), que Warren prefiere. Pero con la etiqueta {own_tag}, el año menos los primeros nueve meses da {on_own_tag}, no {value}: esas cifras no cuadran entre sí. Por eso Warren deja este trimestre como se presentó. Warren no revisó qué incluye cada etiqueta. Ojo: los cuatro trimestres no miden la misma línea y pueden no sumar el año. Con la etiqueta {year_tag}, este trimestre sería {on_year_tag}. Si citas el {form}, usa {value}."

After the changes the real-data scan was run again: 0 differences, 0 kept, 43 on `narrower_tag`; 903 of 903 runs reproduce.

## PR review (nov.12.2026)

Gatekeeper: **GO**. Ruff clean; 2148 passed, 10 skipped; CI green. No test removed or weakened; point-in-time reads unchanged (the second pairing only prefers the quarter's own accession among rows already filtered by `as_of`; no new query); its own scan (three dates, three modes) found no quarter kept. Notes taken at merge: a docstring in `_kept_note` still claimed the quarter was revised (fixed); the minuend words lived in two places (now one, `schemas.MINUEND_WORDS`). Left as is: `_kept_note` would print "None" for a filing missing from the filings list, which cannot happen for a reported fact.

## Files

`domains/fundamentals/schemas.py`, `domains/fundamentals/facts.py`, `domains/analysis/reported.py`, `domains/analysis/math_engine.py`, `domains/fundamentals/quality.py`, `tests/fundamentals/test_quarterly.py`, `tests/fundamentals/test_quality.py`, `tests/analysis/test_reported.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q1 and Q2 (a quarter's figures; notes on a reported figure). No value changes on real data (scan above), and no real quarter gets the new note today.

- **Added:** `tag_note` code `quarter_kept_on_own_tag` (params above). Same place as `quarter_on_year_tag` in group 2 of "Notes on a reported figure": a line carries one or the other, never both. No EDGAR link problem: `form`, `filed_at` and `accession_no` are always set (the line is the filing's own figure).
- **Added:** ratio note `uses_quarter_kept_on_own_tag` (`items`, `periods`), where `uses_quarter_on_year_tag` goes.
- **Changed:** `uses_quarter_on_year_tag` is now given only for lines whose `tag_note` is `quarter_on_year_tag` (before, any `tag_note`; the same lines on real data).
- Nothing renamed or removed.
