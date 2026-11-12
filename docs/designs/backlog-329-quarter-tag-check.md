# Backlog #329: check the quarter's own tag before moving it to the year's

Issue: https://github.com/sonderbot-ar/warren/issues/329 · Branch `backlog-329-quarter-tag-check` · Status: in progress (nov.12.2026).

From the review of #324 (PR #327, `docs/designs/backlog-324-quarter-tags.md`).

## Problem

Since v0.9.55 (#324), a quarter a filing gave only under a tag ranked below its year's tag is replaced by the year less the earlier periods, all on the year's tag (Walmart revenue FY2010Q4 to FY2012Q4: net sales in the 10-K's quarterly note, total revenues everywhere else). Two gaps were left:

1. **No value check (analyst).** The swap trusts the ranking alone. It is safe when the quarter's own tag, derived the same way, gives the reported quarter: then the two tags differ only by line (net sales vs total revenues), not by basis. If a filing revised the quarter on its own tag after the year was filed, the narrow year less the narrow nine months no longer equals the reported quarter, and swapping in the year's-tag derivation would replace a revised figure with an unrevised one. The ranking cannot see that.
2. **Untested path (gatekeeper).** `_with_tag_note` (`domains/analysis/reported.py`) returns the line with no note when the reported lookup does not find the filing's own quarter, although the value has still moved. On real data the lookup always matches (it reads the same rows as the swap), but a silent change of value is the one outcome the note exists to prevent.

Item 3 of the issue (40 derived quarters that still mix two tags) is #295's scope, not this one.

## Plan

**Step 0. This doc.**

**Step 1. The value check** (`domains/fundamentals/facts.py`).

- `_on_year_tag` takes `tagged` (every filing's value of each duration period under each tag it used, `_tagged`, already built for one basis). For each input of the year's-tag derivation (Q4: year and nine months, or year and Q1–Q3; Q3 and Q2 likewise), read the same period under the **quarter's own tag** from **the filing that gave that input** (same accession). If every input has one, the same subtraction on those figures must come within `RECAST_MOVE` (0.5%, the threshold that already finds a recast) of the reported quarter; if not, the quarter is kept as reported (no swap, no `narrower_tag`). If any input's filing lacks the quarter's tag, there is no check and v0.9.55's rule applies, as today.
- Same filing, not newest or earliest: an input's own filing presents both lines side by side, so the pair shares a basis in every mode (latest, first-reported, one basis), and no mode-specific choice is needed.
- `get_facts(frequency="quarterly")` now builds `tagged` in every mode and passes it to `_quarterly`, and `_quarterly` passes it into both calls of `_quarters_for_flow` (the first-reported quarters for one basis, and the main one).
- Tests (`tests/fundamentals/test_quarterly.py`, Test Corp: year 460 and nine months 330 under `Revenues`, Q4 125 under `SalesRevenueNet` in the 10-K): narrow year 450 and nine months 325 (agree: 125) move Q4 to 130 in both modes and with one basis; 450 and 310 (140, disagree) keep 125 as reported in all three; 0.6% off disagrees and 0.4% off agrees; a missing narrow nine months means no check (130); a narrow year from a later 10-K/A is not read for the 10-K's input (no check, 130).
- Exit: full suite passes; the real-data scan below changes nothing.

**Step 2. A note even when the filing's figure is not found** (`domains/analysis/reported.py`).

- `_with_tag_note`: when the fact carries `narrower_tag` but the reported lookup returns nothing, the line still gets `tag_note` (`quarter_on_year_tag`) with the same params, `reported_tag` taken from `narrower_tag`, and `reported_value`, `form`, `filed_at`, `accession_no` set to None. English: "…; the company's filing gives the quarter only under {reported_tag}, a tag Warren ranks below it, so the four quarters would not measure the same line or add up to the year". The ratio note `uses_quarter_on_year_tag` follows as before.
- Test (`tests/analysis/test_reported.py`): with the lookup forced to miss, the line carries the note with those params and the ratio note.
- Exit: full suite passes.

## Real-data scan (Step 1)

Snapshot of nov.10.2026 restored (schema 22). Every duration item, all eight companies, as of 2010-06-01, 2011-06-01, 2012-06-01, 2013-06-01, 2015-06-01, 2019-06-01, 2023-06-01 and 2026-11-09, latest with and without one basis and first-reported, with the check against without it: **0 differences**; 43 quarter-views still carry `narrower_tag`. All three Walmart quarters are checked (each input's filing has the net-sales tag) and pass exactly:

| Quarter | Reported (net sales) | Net-sales year − nine months, from the inputs' own filings |
|---|---|---|
| FY2010Q4 | 112,826 | 405,132 − 292,306 = 112,826 |
| FY2011Q4 | 115,600 | 418,952 − 303,352 = 115,600 |
| FY2012Q4 | 122,285 | 443,854 − 321,569 = 122,285 |

## Alternatives considered

- **Exact equality** (the analyst's "equals"). The real cases are exact, but a figure tagged in millions in one filing and thousands in another would fail on rounding. `RECAST_MOVE` is the engine's existing threshold.
- **The newest narrow version of each input** (or the earliest, in first-reported mode). Ties the check to the mode and can pair a recast narrow year with an unrecast quarter; the same filing avoids both.
- **Step 2 as a test of the silent path only** (the gatekeeper's other option). It would pin a value change with nothing said, which the note exists to prevent.

## Files

`domains/fundamentals/facts.py`, `domains/analysis/reported.py`, `tests/fundamentals/test_quarterly.py`, `tests/analysis/test_reported.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q1 and Q2 (a quarter's figures; notes on a reported figure). No value changes on real data (scan above).

- **Changed:** `tag_note` (`quarter_on_year_tag`) can now arrive with `reported_value`, `form`, `filed_at` and `accession_no` null; `reported_tag` is always set. Never on real data today. The screen should then drop the sentence that cites the filing ("El {form} presentado el {filed_at} da este trimestre como {reported_value}…") and say only that the company's filing gives the quarter under another XBRL tag ({reported_tag}), with no EDGAR link.
- **Changed:** a quarter whose own tag disagrees with its year (more than 0.5%) is shown as reported, with no `tag_note`. None today.
- Nothing added, renamed or removed.
