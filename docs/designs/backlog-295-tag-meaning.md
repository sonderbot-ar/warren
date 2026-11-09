# Backlog #295 item 3: growth across a tag that changed meaning

Issue: https://github.com/sonderbot-ar/warren/issues/295 · Branch `backlog-295-tag-meaning` · Status: in progress (nov.09.2026). Items 1, 2 and 4 of the issue stay open there.

## Problem

Warren picks, for each line and period, the best-ranked tag and that tag's newest filing (Structure Guide Decision 2, "Which version wins"). Ranking the tag first keeps a broader or narrower measure filed under *another* tag from passing as a restatement. It does not catch a company that changes what its *own* best tag means.

Exxon did that. Until 2019 its `us-gaap:Revenues` held sales; from the 10-Q filed 2019-11-06 it holds total revenues and other income, comparatives included. The same filings repeat the old sales figures under `RevenueFromContractWithCustomerExcludingAssessedTax`:

| Exxon revenue | First filed (Revenues) | Later filing (Revenues) | Same later filing, contract-revenue tag |
|---|---|---|---|
| Q3 2018 | 74,187 (10-Q 2018-11-07) | 76,605 (10-Q 2019-11-06) | 74,187 |
| 9 months 2018 | 211,079 | 218,317 (10-Q 2019-11-06) | 211,079 |
| Year 2018 | 279,332 (10-K 2019-02-27) | 290,212 (10-K 2020-02-26) | 279,332 |
| Year 2017 | 237,162 (10-K 2018-02-28) | 244,363 (10-K 2020-02-26) | 237,162 |

Periods refiled after the change carry the new meaning; periods never refiled keep the old one. So growth can compare total revenue with last year's sales: `reported_period(XOM, FY2018Q4, 2026-11-09)` gives +10.1% (71,895 total against 65,312 sales, one basis); on sales alone it is about +4.5%. Nothing told the student.

## Plan

**Step 0. This doc.**

**Step 1. Find a tag that changed meaning (`facts.tag_meaning_changes`).** For each item and period, walk the filings public on `as_of`, oldest first. A filing's best-tag value that moves by more than 0.5% from the same tag's previous version, while the same filing gives another tag of the item the previous value (within 0.1%), is a sign of a new meaning. A change is counted once at least two periods show it (across filings), and dated by the first filing that shows it. Returned as `MeaningChange` (item, tag, other tag, first filing's accession, form and date, and each period's old and new value). `meaning_of(fact, changes)` says whether a fact carries the new meaning: same item, its tag (a derived quarter's tags include it), newest input filed on or after the change. The data quality report gains a section listing the changes. **Values do not change.**

- Tests (`tests/fundamentals/test_meaning_change.py`): found and dated; invisible before the filing; one period alone is not counted (the JNJ case below); a restatement without the old figure is not counted; a 0.4% move is not counted; periods counted across filings, dated by the first; `meaning_of` on the tag, the date and a derived quarter's tags.
- Exit: on the real data, exactly Exxon's revenue is found (7 periods, from the 10-Q of 2019-11-06), and nothing for the other seven companies.

**Step 2. Say so on growth (`reported_period`).** When one of the two periods in `revenue_growth_yoy` carries the new meaning and the other the old, the ratio gains a note `tag_changed_meaning` with params `item`, `tag`, `other_tag`, `changed_on` (ISO date), `form`, `accession_no`, `new_meaning` and `old_meaning` (period labels). The value is unchanged.

- Tests (`tests/analysis/test_reported.py`, Test Corp redefining `Revenues` 4% higher from its Q3 2019 10-Q): the note on FY2019Q1 (new against old); none on FY2019Q3, FY2019Q2 and FY2019 (one meaning each); on FY2018Q3 none on 2019-12-31 (one period public) and the note after the FY2019 10-K.
- Exit: Exxon's notes listed below match the table above.

## Real data (Step 1 and 2, on the snapshot of nov.05.2026, as of 2026-11-09)

- The scan's raw signature (before the two-period rule) fires on 8 periods: Exxon's 7 revenue periods and one JNJ balance, cash at 2023-01-01 (14,127 to 12,889 in the 10-Q of 2023-10-27, the whole 14,127 kept under the restricted-cash tag). JNJ's is the Kenvue separation moving cash to assets held for sale, a restatement, not a new meaning; the two-period rule leaves it out.
- Growth notes, every Exxon period FY2009–FY2026 as of 2026-11-09: five carry `tag_changed_meaning`, each pairing a period refiled after the change with one never refiled: FY2017 (+21.8%, the year 244,363 against FY2016's sales), FY2018Q3 (+29.1%), FY2018Q4 (+10.1%), FY2019Q1 (−2.8%) and FY2019Q2 (−3.3%). None for the other seven companies. Exxon's FY2018 (+18.8%, both years from the 10-K of 2020) and FY2019Q3 onward sit on the new meaning throughout: no note.
- 90 of Exxon's 100 stored runs are dated after 2019-11-06; their history crosses the change for the years it covers (follow-up below).

## Alternatives considered

- **Keep the old meaning (read the other tag for periods after the change).** It would give like-for-like growth, but it changes Decision 2's "which version wins" rule, which is the owner's call (CLAUDE.md), and it would leave Exxon's recent years on a measure the company no longer puts first. Not built; listed under Limits as the question for the owner if the note proves not enough.
- **Compute like-for-like growth on the other tag beside the note.** A second number on the same ratio; useful, but it needs a rule for which periods the other tag covers. Left to the follow-up issue.
- **Flag any best-tag change of more than 0.5%.** That is every restatement (JNJ after Kenvue, KO's recasts); the signature needs the old figure still filed under another tag.
- **One period suffices.** It catches JNJ's cash, a restatement (above).

## Files

`domains/fundamentals/facts.py`, `domains/fundamentals/quality.py`, `domains/analysis/reported.py`, `tests/fundamentals/test_meaning_change.py`, `tests/analysis/test_reported.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q1–Q2 (what a company reported, and how it grew). One note code added on `reported_period(...).ratios["revenue_growth_yoy"].notes`: `tag_changed_meaning`, params as in Step 2, English fallback text "revenue for FY2018Q4 uses us-gaap:Revenues as the 10-Q filed 2019-11-06 redefined it, FY2017Q4 its old meaning (the old figures are still filed under us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax): not like for like". Nothing renamed or removed, no value changes. The app should show it beside the growth figure, as it shows `uses_one_basis_line`; a Spanish sentence is needed (the tag names are proper nouns, kept as is).

## Limits

- Runs read the same numbers, and a run's history can cross Exxon's change; no run note says so yet (follow-up issue).
- Only growth gets the note. A margin uses one period's revenue and is not affected; a track record or forecast error across the change is (follow-up).
- A tag that changes meaning and later changes back, or changes without the old figure being kept under another tag, is not found.
- The two-period rule and the 0.5% and 0.1% thresholds are working rules fitted on one positive (Exxon) and one negative (JNJ) case.

## Where the work stopped

Steps 1 and 2 built with tests; design review and PR next.
