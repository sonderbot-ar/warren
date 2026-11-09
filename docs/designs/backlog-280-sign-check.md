# Backlog #280: skip a version filed with the wrong sign

Issue: https://github.com/sonderbot-ar/warren/issues/280 · Branch `backlog-280-sign-check` · Status: in review (nov.09.2026).

## Problem

For each item and period, Warren uses the newest version public on the as-of date of the best-ranked tag (`facts._latest_of_best_tag`). A company's XBRL tag sometimes carries the wrong sign in one filing while the printed statement is right. Walmart's 10-K for fiscal 2011 (0001193125-11-083157) tagged income tax expense negative for all three years it shows:

| Walmart income tax, year ending | 10-K FY2010 (2010-03-30) | 10-K FY2011 (2011-03-30) | 10-K FY2012 (2012-03-27) | 10-K FY2013 |
|---|---|---|---|---|
| Jan 2009 (FY2008 in the issue) | 7,145 | **−7,133** | — | — |
| Jan 2010 | 7,139 | **−7,156** | 7,156 | — |
| Jan 2011 | — | **−7,579** | 7,579 | 7,579 |

The year ending Jan 2009 has no third version, so the wrong one is the newest forever: on main, every query from 2011-03-30 on reads −7,133 million, and the derived fourth quarter is −12,319 million (first filed it was 1,959). The year ending Jan 2010 reads −7,156 for a year (2011-03-30 to 2012-03-27). #264's sign check uses the newest version as its reference, so it cannot catch a wrong newest version. Every stored run reads 2019 or later quarters, so no stored number uses these years today; a longer history window, or a teaching screen of Walmart's 2009 tax, would.

A scan of every period of every item for the eight companies (all versions, best tag) finds seven periods whose versions disagree in sign:

| Company, item, period | Versions, oldest first (million) | Kind |
|---|---|---|
| WMT income tax, three years above | see above | sign flip, same size |
| CAT cost of revenue, H1 2009 and Q2 2009 | −12,779 then 12,779; −5,752 then 5,752 | sign flip, first version wrong |
| MSFT domestic pretax income, FY2016 | −325, −325, 5,125 | real recast: new size |
| PG discontinued operations, Q2 2015 (Apr–Jun) | −102, then 42 | real restatement: new size |

So a sign flip keeps the size, and the wrong side can be the first version (CAT) or the newest (WMT).

## Plan

- **Step 0.** This design doc.
- **Step 1. Skip a flipped version** (`domains/fundamentals/facts.py`, latest mode). For one period, take each filing's version under the best tag, public on the as-of date.
  1. A version is a *suspect* when another version has the opposite sign and nearly the same size: the sizes differ by at most `SIGN_FLIP_TOLERANCE` = 1% of the other's (WMT 0.2%, CAT 0%; MSFT and PG are far off, so real restatements are left alone).
  2. Among the suspects, the wrong side is the sign fewer of the period's versions take (WMT's Jan 2010 year after 2012: two positive, one negative).
  3. On a tie (two versions, one each way), the wrong side is the one against the item's *usual sign* for the company: the majority sign of the newest best-tag value of every other period of that item public on the as-of date (`_UsualSigns`). Walmart's tax is positive in nearly all its other periods; Caterpillar's cost of revenue in all.
  4. With no usual sign either (an item with only that period, or an even split), nothing is skipped and the newest version is used, as today.
  The newest version not skipped is selected. `restated` still compares it with the first-filed version. `first_reported` mode is unchanged: it means the version public first, flipped or not. `newest_filing_disagreements` (the tag-drift audit) no longer lists a skipped flip, since it is not tag drift; a new `skipped_sign_flips(conn, cik, names, as_of)` lists each skipped version with the one used, and the fundamentals quality report shows them in their own section. Derived quarters need no change: they subtract the selected versions, and #264's one-basis check now sees the right newest sign.
  Tests (`tests/fundamentals/test_facts.py`, `test_quarterly.py`, `test_quality.py`): a flipped newest version with no third version is skipped on the usual sign (WMT Jan 2009); a flipped first version is corrected by the newer one (CAT 2009); with three versions the majority wins over the usual sign, and with two the usual sign decides; no usual sign keeps the newest; a sign change with a new size is a restatement and is kept (MSFT); the 1% boundary (1.0% flips, 1.1% doesn't); a flip is judged only on versions public by the as-of date; first-reported mode keeps a flipped first version; a skipped flip is listed by `skipped_sign_flips` and not by `newest_filing_disagreements`; a derived Q4 subtracts the year with the right sign, with and without one basis; the quality report's section and count.
  Exit: tests pass, full suite green.
- **Step 2. Real data** (snapshot `warren-20261105T101750Z`). `get_facts` on main and on the branch, for all eight companies, every item, on the 137 stored run dates plus 2011-06-01, 2012-06-01 and 2026-11-09, in the reported, quarterly (with and without one basis) and annual views; `skipped_sign_flips` on those dates; `analysis reproduce --all --rebuild` on the branch.
  Exit: the only values that change are Walmart's tax for the years ending Jan 2009 and Jan 2010 and the quarters derived from them; every stored run reproduces and rebuilds exactly.

**Point in time.** The rule reads only versions public on the as-of date (the rows `_rows_by_period` already filters), including for the usual sign. A flip is caught only once a second version is out: on its own, a wrong first version is used until the next filing (Walmart's Jan 2011 year from 2011-03-30 to 2012-03-27; CAT's 2009 costs for a year). That is the price of not using hindsight. **LLMs.** None. **Invariants.** No stored row, output or score changes; reproduce and rebuild are exact (Step 2).

## Results (nov.09.2026)

Over 4,155,696 facts (8 companies × 140 dates × four views), 564 change, all Walmart income tax:

- the year ending Jan 2009: −7,133 → 7,145 million on every date from 2011-03-30 (all 140 dates checked from 2011-06-01 on), in the reported and annual views; its derived fourth quarter −12,319 → 1,959 (with and without one basis);
- the year ending Jan 2010, only between 2011-03-30 and 2012-03-27 (2011-06-01 checked): −7,156 → 7,139; its fourth quarter −12,313 → 1,982 (1,925 with one basis, #264's first-filed fallback, as on main after 2012).

`skipped_sign_flips` on 2026-11-09 lists five skipped versions: Walmart's three years in 0001193125-11-083157 and Caterpillar's H1 and Q2 2009 cost of revenue in 0000018230-09-000331. For Caterpillar and Walmart's Jan 2011 year the newest version already had the right sign, so the value used does not change; they are listed so the audit is complete. MSFT's FY2016 and PG's 2015 periods are not touched.

Stored runs: `analysis reproduce --all --rebuild`: see the PR (every run OK, every rebuild exact).

## Alternatives considered

- **The first-filed version always wins a tie.** Wrong for Caterpillar's 2009 cost of revenue (first filed negative). Rejected.
- **The newest version always wins a tie** (today's rule). Wrong for Walmart's Jan 2009 year, forever. Rejected.
- **A sign set per item in the concept map** (tax positive, costs positive). Simple, but tax can be a benefit, other income and discontinued operations take either sign, and a wrong expected sign would skip correct data across every company. The company's own usual sign adapts to the item and the company. Rejected for now.
- **Drop the size condition** (any version against the majority is skipped). It would skip real restatements that change sign (MSFT FY2016 domestic pretax income had two −325 versions against one 5,125, so a majority rule alone would keep −325, a figure Microsoft replaced). Rejected.
- **Correct first-reported mode too.** First-reported answers "what was public first"; correcting it needs a later filing, which is hindsight on that date. Left as is; the harness's actuals and comparatives keep their meaning.

## Limits

- A flip whose sizes differ by more than 1% (a flip combined with a small restatement) is not caught.
- With only one version, a wrong sign can't be seen (Walmart's Jan 2011 tax for a year).
- An item whose sign genuinely alternates (other income) has a weak usual sign; it decides only a two-version tie of near-equal size and opposite sign, which a real restatement almost never produces.

## Files to change

`domains/fundamentals/facts.py`, `domains/fundamentals/quality.py`, `tests/fundamentals/test_facts.py`, `tests/fundamentals/test_quarterly.py`, `tests/fundamentals/test_quality.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

No call, field, code or English text the app uses is added, renamed or removed. Values change only for Walmart's income tax for the years ending Jan 2009 (from 2011-03-30 on) and Jan 2010 (between 2011-03-30 and 2012-03-27), in any view that reads them (`reported_period` for those years, a run's history if a window ever reached them): the figure is now the one Walmart printed, and its source is the filing that gave it. `reported_period`'s disagreement rows no longer list a skipped flip (it was never tag drift). Brief Q1–Q2 (reported figures) give the right sign for those years; nothing else moves. If the app wants to say a version was skipped, `skipped_sign_flips` holds it; that would be a new request.
