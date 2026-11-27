# Backlog #613 items 2 and 3: say what Coca-Cola's interest still holds

Issue: https://github.com/sonderbot-ar/warren/issues/613 (items 2 and 3, from the #610 analyst and professor) · Branch `backlog-613-ko-interest-caveats` · Version v0.10.56 when merged.

Status: In progress (nov.27.2026).

## Problem

Since v0.10.54 (#610) Coca-Cola's cost of debt takes out of its interest the gain or loss on paying debt off early, where a 10-K tags it for the year (`debt_extinguishment_in_interest`). Two pieces of the same story stay in the interest, and nothing on the chart says so:

1. **FY2013's early payoff charge is not tagged for the year.** The FY2015 10-K (0000021344-16-000050, Item 7, cash flows from financing) says that in 2013 the extinguishment of $2,154 million of long-term debt "resulted in associated charges of $53 million, including hedge accounting adjustments reclassified from accumulated other comprehensive income, in the line item interest expense ... during the year ended December 31, 2013". No 10-K tags a 2013 figure; two 2013 10-Qs tag 23M year to date (0000021344-13-000039, second quarter: "recorded a charge of $ 23 million in the line item interest expense"; 0000021344-13-000050, nine months). So FY2013 keeps its 463M interest, about 0.1 points of cost of debt too high on average debt near 40 billion. Checked in each filing's text on sec.gov, nov.27.2026.
2. **FY2020's and FY2021's hedge reclass stays in.** With the extinguishments, Coca-Cola moved losses on the hedges of the repaid notes out of other comprehensive income into interest expense: "We also incurred charges of $ 25 million as a result of the reclassification of related cash flow hedging balances from AOCI into income" (FY2020 10-K, 0000021344-21-000008, Note 10) and "charges of $ 91 million" for 2021 (FY2021 10-K, 0000021344-22-000009, Note 10). Item 7 totals them with the tagged charges (484M and 650M). The reclass is not tagged apart, so FY2020 (2.29%) and FY2021 (2.43%) still hold 25M and 91M, about 0.06 and 0.21 points.

Warren should not type those amounts in (they would be hand-entered numbers in a cost of debt; the issue says "a caveat row, not a hand-entered number"). It should say on the chart, with the filings, that the year's interest still holds them.

## Plan

**Step 0. This doc.**

**Step 1. Two caveat codes and their notes.**

- `interest_caveats.CAVEAT_CODES` gains `extinguishment_not_tagged` (the year's interest holds a charge for paying debt off early that no annual filing tags, so Warren cannot take it out) and `hedge_reclass_in_interest` (the year's interest holds hedge losses moved out of other comprehensive income with the early payoffs, not tagged apart). `interest_net_of_hedge_gains` keeps its meaning and its rules.
- `interest_caveats.csv` gains two Coca-Cola rows: `KO,extinguishment_not_tagged,2013,2013` citing 0000021344-13-000039, 0000021344-13-000050 and 0000021344-16-000050 with their words; `KO,hedge_reclass_in_interest,2020,2021` citing 0000021344-21-000008 and 0000021344-22-000009. `rate_item` empty. The amounts appear only in the evidence text, as the filings' words.
- The loader refuses, with every problem listed at once as today: a `rate_item` on a code other than `interest_net_of_hedge_gains` (only that note compares a stated rate), and a row of the two new codes whose evidence names no accession (the note is shown only when a cited filing is public on the run's date, so it needs one).
- `caveat_for(ticker, year)` keeps its contract for the hedge note (now: the covering row of code `interest_net_of_hedge_gains`); new `charges_caveats(ticker, year)` returns the covering rows of the two new codes, in file order. Two codes can cover one year.
- `single_values`: new point notes `extinguishment_not_tagged` and `hedge_reclass_in_interest` (in `POINT_NOTES` and `CELL_NOTES`), built in `_cost_of_debt_point` on either branch (with or without the hedge caveat), after `misdated_fact_left_out` and before the others, since they also explain the interest itself. Params: `fiscal_year`, `from_fiscal_year`, `to_fiscal_year`, `cost_of_debt` (the run's own row on the used year, the point's value otherwise, as the other cost-of-debt notes), `evidence_filings` (the row's filings in the #140 shape, only those filed on or before the run's date). **Point in time:** the note is shown only when `evidence_filings` is not empty, so a run dated before any cited filing gets no note. They do not replace `below_risk_free` or `far_from_stated_rate`: the amount is small and the other notes' causes stay true. The cell carries them when the run's own cost-of-debt year is covered.
- No value changes: notes only. `interest_caveats.csv` is not in the reading-rules fingerprint (a note never changes what a run reads), so no `reading_rules.md` row.
- Tests (`tests/analysis/test_interest_caveats.py`, new `tests/analysis/test_charges_caveats.py`): the shipped file loads with the JNJ row and the two KO rows, their years, codes and accessions; each cited accession is Coca-Cola's (CIK prefix 0000021344); the loader refuses a `rate_item` on a new code and a new-code row with no accession; `caveat_for` returns only the hedge row and `charges_caveats` only the new ones; Test Corp with a `hedge_reclass_in_interest` caveat gets the note on its covered years only, after any misdated note, with its params, and on the cell when the run's year is covered; a caveat whose filings are all after the run's date gives no note; the hedge note and a new note can sit on one point; the values are equal with and without the caveat; the codes are in `POINT_NOTES` and `CELL_NOTES`.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot: every Coca-Cola run's cost-of-debt chart at ten years carries `extinguishment_not_tagged` on FY2013 and `hedge_reclass_in_interest` on FY2020 and FY2021 only, FY2020's only on runs dated after the FY2020 10-K (February 2021); the cell carries the hedge reclass note on runs whose own year is FY2020 or FY2021; no other company gets either note; `reproduce --all` to the cent. Exit: as stated, no run row changes.

## Alternatives considered

- **Take the amounts out by hand (53M, 25M, 91M).** It would make the cost of debt closer to right, but it puts typed numbers into a computed figure, which the standing rules keep out: every number comes from a tagged filing through tested code. The caveat says the size in the evidence and lets the student judge.
- **Use the 10-Q year-to-date tag (−23M) for FY2013.** It is less than half the 53M the 10-K text gives and is a nine-month figure; reading it as the year would be a different wrong number.
- **One code for both.** The causes differ (an untagged charge, and a hedge reclass), and the app's sentence differs, so two codes keep the Spanish exact.
- **Show the note whatever the run's date.** The J&J hedge note does, because its cause is in every 10-K from the start; here the FY2013 total is first given in a 10-K filed in 2016, so the note waits for a cited filing.

## Files to change

`domains/analysis/interest_caveats.csv`, `domains/analysis/interest_caveats.py`, `domains/analysis/single_values.py`, `tests/analysis/test_interest_caveats.py`, new `tests/analysis/test_charges_caveats.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`. `docs/structure-guide.md` and `docs/build-plan.md` unchanged (notes on a read-only view; no decision changes).

## Product impact

Serves Q5 (the inputs behind an answer) and the `cost_of_debt` cell on Q3, Q4 and Q8 (`docs/product/brief.md`). Adds two point and cell note codes on the cost-of-debt chart, `extinguishment_not_tagged` and `hedge_reclass_in_interest`, each with params `fiscal_year`, `from_fiscal_year`, `to_fiscal_year`, `cost_of_debt` and `evidence_filings` (#140 shape, with `filer`). Today they show on Coca-Cola's FY2013 point and its FY2020 and FY2021 points and cells. Each needs its Spanish in the brief (title, sentence, lesson), which the front-end team adds after the merge. No value, field or code is renamed or removed; no stored run changes.
