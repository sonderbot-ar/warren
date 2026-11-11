# Backlog #324: a reported quarter under a narrower tag than its year

Issue: https://github.com/sonderbot-ar/warren/issues/324 · Branch `backlog-324-quarter-tags` · Status: design review (nov.11.2026).

## Problem

Walmart's 10-Ks of 2011-03-30 and 2012-03-27 give the fourth quarter only in the quarterly-data note, tagged `us-gaap:SalesRevenueNet` (net sales). The year (`us-gaap:Revenues`, total revenues: net sales plus membership and other income) and every 10-Q's quarter and nine months use `Revenues`. A reported quarter beats a derived one, so Warren shows (snapshot of nov.10.2026, as of 2026-11-09):

| Walmart quarter | Q1–Q3 shown | Q4 shown (net sales, reported) | Q4 on the year's tag (year − nine months) |
|---|---|---|---|
| FY2010 (ends 2011-01-31) | total revenues | 112,826 | 113,622 (+0.7%) |
| FY2011 (ends 2012-01-31) | total revenues | 115,600 | 116,360 (+0.7%) |

So a quarter series, a trailing year built from quarters, and any run dated 2011-03-30 to about 2013 read three quarters of one line and a fourth of a narrower one, with nothing to say so. The sum of the four quarters falls short of the reported year by the membership income (796 and 760 million).

Scan (every duration item, all eight companies, as of 2026-11-09): a reported quarter whose tag ranks below the one tag its year and the periods before it share happens **only on these two Walmart revenue quarters**. No stored run (Walmart's start 2019-04-01) and no evaluation case reads them, so no stored number moves.

This is not #297 item 13 (no figure was recast) nor a tag that changed meaning (`tag_meaning_changes` needs one tag to move). It is #295 item 1 seen from the other side: there, derived quarters mix tags; here, a reported quarter does.

## Plan

**Step 0. This doc.**

**Step 1. The rule** (`domains/fundamentals/facts.py`, `schemas.py`).

- In `_quarters_for_flow`, after the usual placement: a quarter (Q2, Q3 or Q4) that is reported, and shown as reported, is replaced by its derivation when every input of the derivation (Q4: year − nine months, else year − Q1 − Q2 − Q3; Q3: nine months − half, else nine months − Q1 − Q2; Q2: half − Q1; the same order the code already uses) is reported, all inputs carry one tag, and that tag ranks above the quarter's own tag in the concept map for the item. In latest mode with `one_basis` the derivation goes through `_Basis.place` as any derived quarter does.
- The replaced quarter is a derived fact as any other (`derived`, `inputs`, `xbrl_concept` "Revenues − Revenues", `filed_at` its newest input) plus a new field `Fact.narrower_tag`: the tag of the reported quarter it replaces (`us-gaap:SalesRevenueNet`). None everywhere else.
- Applies in latest and first-reported mode (first-reported uses each input as first filed, so Walmart's FY2010Q4 is 113,622 there too). The rule never makes a value from a tag the concept map does not list for the item, and never replaces a quarter whose inputs are themselves derived.
- Tests (`tests/fundamentals/test_quarterly.py`, Test Corp): a 10-K gives Q4 only under the item's third-ranked tag while the year and the nine months use the first: Q4 is the derivation, `narrower_tag` names the third tag, in both modes and with `one_basis`; Q4 under the same tag as the year is kept as reported; Q4 under a higher-ranked tag than the year is kept; inputs on two tags keep the reported quarter; a Q3 case (nine months − half) works the same way; before the year is public no Q4 exists, as today.
- Exit: full suite passes.

**Step 2. Say so** (`domains/analysis/reported.py`, `math_engine.trace`, `sources.filing`).

- The run trace adds "(its own filing tags it only under {tag}, a narrower line than the year's; worked out from the year instead)".
- A source row gains `narrower_tag` (absent on rows stored before, which means None).
- `reported_period(...).lines` and `prior_lines`: a line gains `tag_note`, a coded note `quarter_on_year_tag` with params `item`, `period`, `value`, `reported_value`, `reported_tag`, `tag`, `form`, `accession_no` (the filing that gave the narrower figure), and English text: "revenue FY2010Q4 is 113,622, the year less the nine months, all on Revenues; the 10-K filed 2011-03-30 gives the quarter as 112,826, but only under SalesRevenueNet, a narrower line than the year and the other quarters use". Ratios that use such a line get `uses_quarter_on_year_tag` (`items`, `periods`), as `uses_one_basis_line` does.
- Tests: the reported view of Test Corp's case carries the note and the ratio note; the trace and source row carry the tag.
- Exit: full suite passes; ruff clean.

**Step 3. Real data** (snapshot of nov.10.2026). Walmart's two quarters as above; the scan finds nothing else; `reproduce --all` (stored runs reproduce, none read these quarters); results below.

## Alternatives considered

- **A note only, values kept** (the issue's first option). The quarter would still be on the wrong line for every run and series, and Q1–Q4 would not add up to the year. A note explains an error the data lets us avoid.
- **Rank SalesRevenueNet above Revenues.** Wrong for Walmart's other periods and for every company that tags a contract-revenue subtotal (concept map note).
- **Re-derive only under `one_basis`** (as #290 did for `_paired_tag`). Leaves the reported view, first-reported actuals and the series on the mix; the bug is not about bases.
- **Fix every mixed-tag derivation now** (#295 item 1). Larger (40 derived quarters across items mix two tags, mostly D&A at P&G and Walmart, many where the two tags mean the same), and changes run inputs; stays in #295.

## Decision 2

Decision 2 picks, for each period, the highest-ranked tag that reports it, then its newest filing. That rule is unchanged: it still picks `SalesRevenueNet` as the only version reported *for that quarter*. What changes is the quarterly view's choice between a reported quarter and a derived one (`_quarters_for_flow`, M1's "deriving the ones not reported"), which Decision 2 does not set: a derived quarter on the year's higher-ranked tag now beats a reported one on a lower-ranked tag, which is Decision 2's own reason for ranking tags first ("a later filing repeating the period under a broader or narrower measure" is definition drift, not a different figure). If a reviewer reads this as a change to Decision 2, it goes to the owner as a card and this stays on the branch.

## Files

`domains/fundamentals/facts.py`, `domains/fundamentals/schemas.py`, `domains/analysis/reported.py`, `domains/analysis/math_engine.py`, `domains/analysis/sources.py`, `domains/analysis/__main__.py` (terminal line), `tests/fundamentals/test_quarterly.py`, `tests/analysis/test_reported.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q1 and Q2 (a quarter's figures and a series of quarters): Walmart's FY2010Q4 and FY2011Q4 revenue now sit on the same line as the other quarters, and the four quarters add up to the year.

- **Value change:** two figures, Walmart revenue FY2010Q4 (112,826 → 113,622) and FY2011Q4 (115,600 → 116,360), in the reported view, series and any run dated when they are in its history. No stored run or score reads them.
- **Added:** `Line.tag_note` (code `quarter_on_year_tag`), ratio note `uses_quarter_on_year_tag`, source field `narrower_tag`. Nothing renamed or removed.
- Note order for the side panel (brief, "Notes on a reported figure"): this is a "why it comes from where it does" note, so it goes with the sign and one-basis notes, before `changed`.

## Limits

- Only quarters whose inputs are all reported and share one tag. A quarter that also has derived inputs keeps the reported figure.
- The rule trusts the concept map's ranking; it does not check that the narrower tag is narrower by value.
