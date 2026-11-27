# Backlog #613 items 2 and 3: say what Coca-Cola's interest still holds

Issue: https://github.com/sonderbot-ar/warren/issues/613 (items 2 and 3, from the #610 analyst and professor) · Branch `backlog-613-ko-interest-caveats` · Version v0.10.56 when merged.

Status: In progress (nov.27.2026).

## Problem

Since v0.10.54 (#610) Coca-Cola's cost of debt takes out of its interest the gain or loss on paying debt off early, where a 10-K tags it for the year (`debt_extinguishment_in_interest`). Two pieces of the same story stay in the interest, and nothing on the chart says so:

1. **FY2013's early payoff charge is not tagged for the year.** The FY2013 10-K (0000021344-14-000008, Item 7) says "Interest expense was $463 million in 2013 ... primarily due to charges of $53 million the Company recorded on the early extinguishment of certain long-term debt", and its financing section, like the FY2015 10-K's (0000021344-16-000050), says the charges, "including hedge accounting adjustments reclassified from accumulated other comprehensive income", were "in the line item interest expense". No 10-K tags a 2013 figure; two 2013 10-Qs tag 23M year to date (0000021344-13-000039, second quarter: "recorded a charge of $ 23 million in the line item interest expense"; 0000021344-13-000050, nine months). So FY2013 keeps its 463M interest, about 0.1 points of cost of debt too high on average debt near 40 billion. Checked in each filing's text on sec.gov, nov.27.2026.
2. **FY2020's and FY2021's hedge reclass stays in.** With the extinguishments, Coca-Cola moved losses on the hedges of the repaid notes out of other comprehensive income into interest expense: "We also incurred charges of $ 25 million as a result of the reclassification of related cash flow hedging balances from AOCI into income" (FY2020 10-K, 0000021344-21-000008, Note 10) and "charges of $ 91 million" for 2021 (FY2021 10-K, 0000021344-22-000009, Note 10). Note 10 says only "into income"; Item 7 places them in interest expense, totalling them with the tagged charges: "charges of $484 million" (2020, 459 + 25) and "$650 million" (2021, 559 + 91). The reclass is not tagged apart, so FY2020 (2.29%) and FY2021 (2.43%) still hold 25M and 91M, about 0.06 and 0.21 points.

Warren should not type those amounts in (they would be hand-entered numbers in a cost of debt; the issue says "a caveat row, not a hand-entered number"). It should say on the chart, with the filings, that the year's interest still holds them.

## Plan

**Step 0. This doc.**

**Step 1. Two caveat codes and their notes.**

- `interest_caveats.CAVEAT_CODES` gains `extinguishment_not_tagged` (the year's interest holds a charge for paying debt off early that no annual filing tags, so Warren cannot take it out) and `hedge_reclass_in_interest` (the year's interest holds hedge losses moved out of other comprehensive income with the early payoffs, not tagged apart). `interest_net_of_hedge_gains` keeps its meaning and its rules.
- `interest_caveats.csv` gains two Coca-Cola rows: `KO,extinguishment_not_tagged,2013,2013` citing the FY2013 10-K (0000021344-14-000008) first, then the two 2013 10-Qs (0000021344-13-000039, -13-000050); `KO,hedge_reclass_in_interest,2020,2021` citing 0000021344-21-000008 and 0000021344-22-000009, each with its Note 10 and Item 7 words. `rate_item` empty. For these codes the evidence opens with an accession and each accession is followed by that filing's own quoted words (`InterestCaveat.quotes`), so the app can show the words of only the filings public on a run's date. The amounts appear only in those quotes.
- The loader refuses, with every problem listed at once as today: a `rate_item` on a code other than `interest_net_of_hedge_gains` (only that note compares a stated rate), and a row of the two new codes whose evidence does not open with an accession (the note is shown only when a cited filing is public on the run's date, and quotes each one apart).
- `caveat_for(ticker, year)` keeps its contract for the hedge note (now: the covering row of code `interest_net_of_hedge_gains`); new `charges_caveats(ticker, year)` returns the covering rows of the two new codes, in file order. Two codes can cover one year.
- `single_values`: new point notes `extinguishment_not_tagged` and `hedge_reclass_in_interest` (in `POINT_NOTES` and `CELL_NOTES`), built in `_cost_of_debt_point` on either branch (with or without the hedge caveat), after `misdated_fact_left_out` and before the others, since they also explain the interest itself. Params: `fiscal_year`, `from_fiscal_year`, `to_fiscal_year`, `cost_of_debt` (the run's own row on the used year, the point's value otherwise, as the other cost-of-debt notes), `evidence_filings` (the row's filings in the #140 shape, only those filed on or before the run's date) and `evidence` (the same filings, each `{filing, quote}` with the filing's own words in English, so a run dated in 2013 quotes only the 10-Q's $23 million; product lead). **Direction:** both codes always mean a charge that makes the cost of debt read higher than the interest on the debt; J&J's `interest_net_of_hedge_gains` means the opposite, so their wording must not be shared (product lead). **Point in time:** the note is shown only when `evidence_filings` is not empty, so a run dated before any cited filing gets no note. They do not replace `below_risk_free` or `far_from_stated_rate`: the amount is small and the other notes' causes stay true. The cell carries them when the run's own cost-of-debt year is covered.
- No value changes: notes only. `interest_caveats.csv` is not in the reading-rules fingerprint (a note never changes what a run reads), so no `reading_rules.md` row.
- Tests (`tests/analysis/test_interest_caveats.py`, new `tests/analysis/test_charges_caveats.py`): the shipped file loads with the JNJ row and the two KO rows, their years, codes and accessions; each cited accession is Coca-Cola's (CIK prefix 0000021344); the loader refuses a `rate_item` on a new code and a new-code row with no accession; `caveat_for` returns only the hedge row and `charges_caveats` only the new ones; Test Corp with a `hedge_reclass_in_interest` caveat gets the note on its covered years only, after any misdated note, with its params, and on the cell when the run's year is covered; a caveat whose filings are all after the run's date gives no note; the hedge note and a new note can sit on one point; the values are equal with and without the caveat; the codes are in `POINT_NOTES` and `CELL_NOTES`.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot: every Coca-Cola run's cost-of-debt chart at ten years carries `extinguishment_not_tagged` on FY2013 and `hedge_reclass_in_interest` on FY2020 and FY2021 only, FY2020's only on runs dated after the FY2020 10-K (February 2021); the cell carries the hedge reclass note on runs whose own year is FY2020 or FY2021; no other company gets either note; `reproduce --all` to the cent. Exit: as stated, no run row changes.

## Results (Step 2, nov.27.2026)

On the restored snapshot `warren-20261127T002823Z`, every one of Coca-Cola's 115 stored runs and the newest run of each other company, the cost-of-debt chart at ten years:

- **FY2013** carries `extinguishment_not_tagged` on 60 runs, 2019-04-01 to 2023 (later ten-year charts start after FY2013), quoting the FY2013 10-K and the two 2013 10-Qs.
- **FY2020** carries `hedge_reclass_in_interest` on 87 runs, from 2021-03-01, the first run date after the FY2020 10-K (filed 2021-02-25); **FY2021** on 71 runs, from 2022-03-01, after the FY2021 10-K (2022-02-22). On runs dated between the two 10-Ks, FY2020's note quotes only the FY2020 10-K.
- **The cell** carries `hedge_reclass_in_interest` on 30 runs whose own cost-of-debt year is FY2020 (16) or FY2021 (14), followed by `far_from_stated_rate` (these stored runs, dated before #610, still hold the whole charge in their row; #618).
- No other year and no other company carries either note; no run errors. On the newest run (2026-10-30) FY2020's and FY2021's points carry only the new note.
- No value changes (notes only; `test_the_values_are_the_same_with_and_without_the_caveat`). No data was added, so no new snapshot.

## Design review (nov.27.2026)

- **Explainer.** Twelve gaps, all wording or already in the code: `caveat_for` filters by code, the cell list is extended, "before the others" means ahead of `below_risk_free` and `far_from_stated_rate`, any one public cited filing is enough. A run dated before the FY2021 10-K has no FY2021 point to carry a note (the year reads `not_filed_yet`).
- **Analyst, GO after one blocker, taken.** The FY2013 10-K itself (0000021344-14-000008, filed 2014-02-27) gives the 53M; the draft cited only the FY2015 10-K and claimed the total was first given in 2016. Now cited first. Taken: quote Item 7, which places the reclass in interest expense (Note 10 says only "into income"); the `evidence` param in the doc. Checked: all five accessions are in the snapshot's facts, so their dates resolve. No other Phase 1 company needs a row (AAPL, MSFT, JNJ, XOM and CAT tag no extinguishment; P&G and Walmart book theirs outside interest). Filed as a backlog idea: a stored run dated before #610 still holds the whole charge in its own row, so its cell note says less than the truth (the point already carries `run_read_differently`).
- **Professor, GO.** ASC 470-50-40-2 (the gain or loss belongs to the year of the payoff), ASC 815-30-40-4/5 (a hedge's balance in other comprehensive income moves to earnings when the hedged payments will not happen) and ASC 815-20-45-1B (no required line, so it is Coca-Cola's choice) support a note rather than a hand adjustment; a book cost of debt is a proxy (Koller et al., *Valuation*, 2020; Damodaran, *Investment Valuation*, 2012) and 0.06 to 0.21 points sit inside its noise. Lesson idea, for the brief: part of the reclass is interest paid early, so "reads high" is an upper bound.
- **Product lead, GO with the `evidence` param (taken) and the direction stated (taken).** Spanish proposed: "Incluye un cargo por liquidar deuda anticipadamente" and "Incluye pérdidas de coberturas", with sentences ending "este costo de la deuda puede verse algo más alto de lo que la empresa paga por su deuda"; the front-end team adds them to the brief with `misdated_fact_left_out`'s.

## Alternatives considered

- **Take the amounts out by hand (53M, 25M, 91M).** It would make the cost of debt closer to right, but it puts typed numbers into a computed figure, which the standing rules keep out: every number comes from a tagged filing through tested code. The caveat says the size in the evidence and lets the student judge.
- **Use the 10-Q year-to-date tag (−23M) for FY2013.** It is less than half the 53M the 10-K text gives and is a nine-month figure; reading it as the year would be a different wrong number.
- **One code for both.** The causes differ (an untagged charge, and a hedge reclass), and the app's sentence differs, so two codes keep the Spanish exact.
- **Show the note whatever the run's date.** The J&J hedge note does, because its cause is in every 10-K from the start; here the note waits for a cited filing, and quotes only the public ones (the 2013 10-Qs give 23M year to date before the FY2013 10-K gives 53M).

## Files to change

`domains/analysis/interest_caveats.csv`, `domains/analysis/interest_caveats.py`, `domains/analysis/single_values.py`, `tests/analysis/test_interest_caveats.py`, new `tests/analysis/test_charges_caveats.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`. `docs/structure-guide.md` and `docs/build-plan.md` unchanged (notes on a read-only view; no decision changes).

## Product impact

Serves Q5 (the inputs behind an answer) and the `cost_of_debt` cell on Q3, Q4 and Q8 (`docs/product/brief.md`). Adds two point and cell note codes on the cost-of-debt chart, `extinguishment_not_tagged` and `hedge_reclass_in_interest`, each with params `fiscal_year`, `from_fiscal_year`, `to_fiscal_year`, `cost_of_debt`, `evidence_filings` (#140 shape, with `filer`) and `evidence` (list of `{filing, quote}`, English, public filings only). Both mean the cost of debt reads a little high. Once merged they show on Coca-Cola's FY2013 point and its FY2020 and FY2021 points and cells. Each needs its Spanish in the brief (title, sentence, lesson), which the front-end team adds after the merge. No value, field or code is renamed or removed; no stored run changes.
