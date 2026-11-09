# Backlog #280: skip a version filed with the wrong sign

Issue: https://github.com/sonderbot-ar/warren/issues/280 · Branch `backlog-280-sign-check` · Status: built, in review (nov.09.2026). Steps 0–2 done; merge waits for the owner's answer on Decision 2 (below).

## Problem

For each item and period, Warren uses the newest version public on the as-of date of the best-ranked tag (`facts._latest_of_best_tag`). Years below are named by the month they end, as Walmart's fiscal year ends in January; the issue's "FY2008" is the year ending Jan 2009, and the code's comments use the same fiscal-year labels as the issue. A company's XBRL tag sometimes carries the wrong sign in one filing while the printed statement is right. Walmart's 10-K for fiscal 2011 (0001193125-11-083157) tagged income tax expense negative for all three years it shows:

| Walmart income tax, year ending | 10-K FY2010 (2010-03-30) | 10-K FY2011 (2011-03-30) | 10-K FY2012 (2012-03-27) | 10-K FY2013 |
|---|---|---|---|---|
| Jan 2009 (FY2008 in the issue) | 7,145 | **−7,133** | — | — |
| Jan 2010 | 7,139 | **−7,156** | 7,156 | — |
| Jan 2011 | — | **−7,579** | 7,579 | 7,579 |

The year ending Jan 2009 has no third version, so the wrong one is the newest forever: on main, every query from 2011-03-30 on reads −7,133 million, and the derived fourth quarter is −12,319 million (first filed it was 1,959). The year ending Jan 2010 reads −7,156 for a year (2011-03-30 to 2012-03-27). #264's sign check uses the newest version as its reference, so it cannot catch a wrong newest version. Every stored run's history starts in 2016 or later, so no stored number uses these years today; a longer history window, or the reported view (brief Q1–Q2, `docs/product/brief.md`) asked for Walmart's 2009 tax, would.

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
  3. When the period's versions split evenly (two versions one each way, or two and two), the wrong side is the one against the item's *usual sign* for the company: the majority sign, over every other period of that item, of its newest best-tag value public on the as-of date, taken as filed (a flipped version elsewhere counts as it is; WMT's three flipped years against about 70 positive periods) (`_UsualSigns`, `facts.py:124`). Walmart's tax is positive in nearly all its other periods; Caterpillar's cost of revenue in all.
  4. When the other periods split evenly too (or there are none), nothing is skipped and the newest version is used, as today.
  The newest version not skipped is selected. `restated` still compares it with the first-filed version. `first_reported` mode is unchanged: it means the version public first, flipped or not. `newest_filing_disagreements` (the tag-drift audit) no longer lists a skipped flip, since it is not tag drift; a new `skipped_sign_flips(conn, cik, names, as_of)` lists each skipped version with the one used, and the fundamentals quality report shows them in their own section. Derived quarters need no change: they subtract the selected versions. #264's one-basis rule (`_Basis.place`) skips versions of the year whose sign differs from the selected one, so with the right sign selected the two rules agree (Walmart's Jan 2009 Q4 is 1,959 with and without one basis). The quality report's new section lists each skipped version with the one used, for every year (the report's other sections cover 2016–2025, and every real flip is from 2008–2011), amounts in millions for money and as filed for other units.
  Tests (`tests/fundamentals/test_facts.py`, `test_quarterly.py`, `test_quality.py`): a flipped newest version with no third version is skipped on the usual sign (WMT Jan 2009); a flipped first version is corrected by the newer one (CAT 2009); with three versions the majority wins over the usual sign, and with two the usual sign decides; no usual sign keeps the newest; a sign change with a new size is a restatement and is kept (MSFT); the 1% boundary (1.0% flips, 1.1% doesn't); a flip is judged only on versions public by the as-of date; first-reported mode keeps a flipped first version; a skipped flip is listed by `skipped_sign_flips` and not by `newest_filing_disagreements`; a derived Q4 subtracts the year with the right sign, with and without one basis; the quality report's section and count.
  Exit: tests pass, full suite green.
- **Step 2. Real data** (snapshot `warren-20261105T101750Z`). `get_facts` on main and on the branch, for all eight companies, every item, on the 137 stored run dates plus 2011-06-01, 2012-06-01 and 2026-11-09, in the reported, quarterly (with and without one basis) and annual views; `skipped_sign_flips` on those dates; `analysis reproduce --all --rebuild` on the branch.
  Exit: the only values that change are Walmart's tax for the years ending Jan 2009 and Jan 2010 and the quarters derived from them; every stored run reproduces and rebuilds exactly.

**Point in time.** The rule reads only versions public on the as-of date (the rows `_rows_by_period` already filters), including for the usual sign. A flip is caught only once a second version is out: on its own, a wrong first version is used until the next filing (Walmart's Jan 2011 year from 2011-03-30 to 2012-03-27; CAT's 2009 costs for a year). That is the price of not using hindsight. **LLMs.** None. **Invariants.** No stored row, output or score changes, because no stored run's window reaches 2008–2011; reproduce and rebuild give the same result as main (Step 2). A window that did reach those years would get the corrected figure.

## Results (nov.09.2026)

The 137 stored run dates run from 2019-04-01 to 2026-11-02, all after 2012-03-27, so on them only the Jan 2009 year can change. Over 4,155,696 facts (8 companies × 140 dates × four views: reported, quarterly, quarterly with one basis, annual), 564 change, all Walmart income tax: 140 dates × 4 views for the Jan 2009 year (the year in reported and annual, its Q4 in both quarterly views) = 560, plus the Jan 2010 year's 4 on 2011-06-01:

- the year ending Jan 2009: −7,133 → 7,145 million on every date from 2011-03-30 (all 140 dates checked from 2011-06-01 on), in the reported and annual views; its derived fourth quarter −12,319 → 1,959 (with and without one basis);
- the year ending Jan 2010, only between 2011-03-30 and 2012-03-27 (2011-06-01 checked): −7,156 → 7,139; its fourth quarter −12,313 → 1,982 (1,925 with one basis, #264's first-filed fallback, as on main after 2012).

`skipped_sign_flips` on 2026-11-09 lists five skipped versions: Walmart's three years in 0001193125-11-083157 and Caterpillar's H1 and Q2 2009 cost of revenue in 0000018230-09-000331. For Caterpillar and Walmart's Jan 2011 year the newest version already had the right sign, so the value used does not change; they are listed so the audit is complete. MSFT's FY2016 and PG's 2015 periods are not touched.

Stored runs, `analysis reproduce --all --rebuild`, on main and on the branch: 903 of 903 reproduce to the cent on both; 821 of 903 rebuild to identical rows on both, and the 82 that differ are the same runs with the same lines on both (the runs stored before #264's one-basis fix, v0.9.41). So this change moves no stored run.

## Alternatives considered

- **The first-filed version always wins a tie.** Wrong for Caterpillar's 2009 cost of revenue (first filed negative). Rejected.
- **The newest version always wins a tie** (today's rule). Wrong for Walmart's Jan 2009 year, forever. Rejected.
- **A sign set per item in the concept map** (tax positive, costs positive). Simple, but tax can be a benefit, other income and discontinued operations take either sign, and a wrong expected sign would skip correct data across every company. The company's own usual sign adapts to the item and the company. Rejected for now.
- **Drop the size condition** (any version against the majority is skipped). It would skip real restatements that change sign (MSFT FY2016 domestic pretax income had two −325 versions against one 5,125, so a majority rule alone would keep −325, a figure Microsoft replaced). Rejected.
- **Keep the newest version and correct its sign** (+7,133 for Walmart's Jan 2009 year, which the FY2011 10-K printed; the 10-K before printed 7,145). It would keep "latest" meaning the newest filing and keep the small revision. Rejected: +7,133 is a number no stored XBRL fact holds, so its source would be a fact Warren made up from a tag it has just judged wrong (Structure Guide, principles on traceable numbers); skipping uses a version a filing really tagged. The 12 million (0.2%) revision is lost for this year, and said so under Product impact.
- **The usual sign before the majority** (analyst idea). It survives an error copied into two later filings (wrong, wrong, right), where the majority keeps the wrong sign; but it gets a genuinely unusual period wrong (a tax benefit in a loss year flipped in one comparative: −192, +192, −192 with tax usually positive). Both orders give the same answer on all five real flips. Kept the majority first, because it is simpler to explain and uses the period's own filings before the company's other years; copy-forward is listed under Limits.
- **Correct first-reported mode too.** First-reported answers "what was public first"; correcting it needs a later filing, which is hindsight on that date. Left as is; the harness's actuals and comparatives keep their meaning.

## Limits

- A flip whose sizes differ by more than 1% (a flip combined with a small restatement) is not caught.
- With only one version, a wrong sign can't be seen: Walmart's Jan 2011 tax for a year, and Caterpillar's H1 2008 and Q2 2008 cost of revenue (−18,645 and −10,036 million, from the same bad 10-Q 0000018230-09-000331, never refiled), which stay wrong against 128 positive periods (analyst). A later item could flag a lone version against a strong usual sign, for audit only.
- **Copy-forward.** If two later filings repeat a wrong sign and only one has the right one, the majority keeps the wrong sign. Not seen in the eight companies.
- **Why 1%.** Rounding plus a small revision between filings: the real flips differ by 0.0–0.24%; the nearest real sign disagreement that is not a flip (PG's Q2 2015 discontinued operations, −102 then 42) is far off. No published threshold; it is a working rule.
- **Labels.** In first-reported mode, or when a flipped first version is corrected (CAT 2009), the fact is marked `restated`, which in accounting means an ASC 250 restatement; a tagging correction is not one (professor; idea filed).
- An item whose sign genuinely alternates (other income) has a weak usual sign; it decides only a two-version tie of near-equal size and opposite sign, which a real restatement almost never produces.

## Files to change

`docs/structure-guide.md` (Decision 2, "Which version wins", and its log row; owner's answer first), `domains/fundamentals/facts.py`, `domains/fundamentals/quality.py`, `tests/fundamentals/test_facts.py`, `tests/fundamentals/test_quarterly.py`, `tests/fundamentals/test_quality.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

No call, field, code or English text the app uses is added, renamed or removed. Values change only for Walmart's income tax for the years ending Jan 2009 (from 2011-03-30 on) and Jan 2010 (between 2011-03-30 and 2012-03-27), in any view that reads them (`reported_period` for those years, brief Q1–Q2; a run's history if a window ever reached them). What a student would see there, and what goes unexplained for now (product lead review):

- The figure has the right sign, but it comes from an **older filing** than the newest: for the Jan 2009 year, 7,145 million from the FY2010 10-K, though the FY2011 10-K came later (it printed 7,133 and tagged −7,133). So "latest" in `reported_period` (its note "each uses the latest value known on the as-of date", `reported.py:40-46`, and `value`'s comment, `reported.py:116`) now means the newest version with a believable sign.
- The **revised flag goes off** for that year: `changed` (`reported.py:119`) compares the value used with the first-filed one, both 7,145 now, so the 12 million revision in the FY2011 10-K is not flagged. On main it was flagged, with the wrong sign.
- **Nothing tells the student why.** Disagreement rows never showed this (on main the selected and the newest version were the same row); with the skip they would, and `newest_filing_disagreements` leaves a skipped flip out on purpose because it is not tag drift. `skipped_sign_flips` holds it, but `reported_period` does not call it. Filed now as a `front-end` request: a coded note on `reported_period` (and in the terminal output, `domains/analysis/__main__.py:276-279`) naming the skipped filing, so the source panel can teach that a tag can disagree with the printed statement and Warren followed the print.

## Design review (nov.09.2026)

Explainer, analyst, professor and product lead, as fresh-context subagents, on the first draft.

- **Analyst: GO, no blockers.** Every period of every item for the eight companies, all tags: only the five named versions are skipped; MSFT FY2016 and PG's discontinued operations untouched; point in time checked on every filing date (each skip appears the day the second version is filed, never earlier); the only cross-tag sign disagreement (PG Jul–Sep 2014) sits under a lower tag and is rightly ignored. Ideas taken: the CAT 2008 lone wrong versions and copy-forward under Limits; the quality section now lists flips in every year (it would have said "None." for every company); amounts keep their unit. Idea weighed and not taken: the usual sign before the majority (Alternatives). Filed: #283.
- **Professor: two doc blockers, taken.** (1) The rule changes Decision 2's "which version wins" (the newest filing of the best tag): the Structure Guide is amended in this PR and the change goes to the owner first (CLAUDE.md). (2) The missing alternative, correcting the newest version's sign (+7,133), is now under Alternatives, rejected for provenance. Sources for the method: Debreceny et al. (2010, *JAPP*), Du, Vasarhelyi & Zheng (2013, *JIS*) on sign errors as a main XBRL error type; SEC staff observations on negative values; Croushore & Stark (2001) on vintages. Ideas taken: the 1% rule explained, copy-forward listed, `restated` wording in #282; DQC_0015 cross-check in #283.
- **Product lead: three blockers, taken.** "Latest" can now be an older filing and the revised flag goes off for Walmart's Jan 2009 year, with nothing telling the student: now stated plainly in Product impact, and filed as #282 (`backlog`, `front-end`). The wrong sentence about disagreement rows is reworded.
- **Explainer: gaps, taken.** The even-split rule matches the code (any even split of the period's versions, not only two); which split "no usual sign" means; the invariant stated with its condition; the stored run dates' span; the Step 2 result written here; the year labels; Brief Q1–Q2 named; the quality section described; the 564 broken down.
