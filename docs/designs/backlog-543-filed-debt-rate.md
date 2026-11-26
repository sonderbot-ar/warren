# Backlog #543: flag a cost of debt far from the rate the company states on its own debt

Issue: https://github.com/sonderbot-ar/warren/issues/543 (item 3 of #540, from the #533 analyst) · Branch `backlog-543-filed-debt-rate` · Version v0.10.53 when merged.

Status: In progress (nov.26.2026). Steps 0 to 2 done; PR open.

## Problem

Warren's cost of debt (D8, `docs/build-plan.md` line 196) is a fiscal year's interest over the average of its two year-end debts (`math_engine.cost_of_debt_year`). It is a book figure, and it can be far from what the company pays on its borrowing when the interest line holds something besides interest on the debt. Nothing told a reader so, except for J&J, whose cost-of-debt chart has carried `interest_net_of_hedge_gains` since #542 (v0.10.35), with the rate J&J states on its long-term debt beside it. `cost_of_debt_out_of_bounds` (outside 0% to 15%) catches neither case below.

**Coca-Cola FY2020 and FY2021.** D8 reads 3.36% and 3.73%, while Coca-Cola states about 1.6% on its debt. Its FY2021 10-K (0000021344-22-000009, Note 10) says the early extinguishments of long-term debt "resulted in associated charges of $559 million [2021] / $459 million [2020] recorded in the line item interest expense" (Item 7 totals: $650M and $484M). Without the $650M, FY2021 reads about 2.21%, still +0.6 points: the charges explain most of the gap, not all (analyst).

Three companies state, in the 10-K's debt note, a weighted average rate on their debt, tagged without a dimension, so Warren can read it point-in-time like any fact (company facts, nov.26.2026; analyst checked each against the filings):

| Company | Long-term rate | Short-term rate | What the short-term rate covers |
|---|---|---|---|
| Coca-Cola | `LongtermDebtWeightedAverageInterestRate`, FY2016 on: the weighted-average effective rate on long-term debt before its current portion is taken out, adjusted for swaps | `ShortTermDebtWeightedAverageInterestRate`, FY2009 on: commercial paper | short-term borrowings and commercial paper (the loans and notes payable line, which also holds 845M of other short-term lines at 2021-12-31) |
| P&G | `LongtermDebtWeightedAverageInterestRate`, FY2014 on: long-term debt after the current portion, with swaps | `ShortTermDebtWeightedAverageInterestRate`: "Debt due within one year" (FY2022 10-K, 0000080424-22-000064) | short-term borrowings, commercial paper and the current portion of long-term debt |
| J&J | `DebtInstrumentInterestRateEffectivePercentage`, FY2011 to FY2024 (already read as `debt_effective_rate`, #542): the notes subtotal, current portion included | none Warren reads (its paper was at 0.11% in FY2021, not tagged) | the long-term rate stands for all its debt, which reads high when paper is a large share |

Apple, Walmart and Exxon state only a short-term rate (Exxon's long-term 3.43% is tagged only with a dimension); Microsoft and Caterpillar state neither. None of the three companies' rates is restated in a later 10-K (every year end agrees across filings, analyst). The rates are rounded (Coca-Cola's to 0.1%, so ±0.05 points each).

This item adds a check, not a method: D8, the WACC and every number stay as they are.

## Plan

**Step 0. This doc.**

**Step 1. The stated rates as data, and the note on the cost-of-debt chart.**

- Map, the reported-only file (`concept_map_reported.csv`, outside the valuation map's fingerprint, never read by a valuation): `debt_average_rate_long_term` (`LongtermDebtWeightedAverageInterestRate`) and `debt_average_rate_short_term` (`ShortTermDebtWeightedAverageInterestRate`), unit `pure`, instant, optional, KO and PG only. J&J's long-term rate is the existing `debt_effective_rate`.
- Companies as data (Decision 11): `domains/analysis/stated_debt_rates.csv` (`ticker, long_rate_item, short_rate_item, short_rate_covers, evidence`) and its loader `stated_debt_rates.py`, validated like `interest_caveats.csv` (known ticker, reported-only items, a closed `short_rate_covers` set, `short_term_borrowings` or `due_within_one_year`, an accession in the evidence). Rows: KO (`short_term_borrowings`), PG (`due_within_one_year`), JNJ (no short-term rate).
- `financial_math.blended_rate(long_rate, long_amount, short_rate, short_amount)`: two rates weighted by the amounts they cover, refusing a negative amount or a zero total; property tests (between its two rates, either rate alone when the other amount is zero, the same in any unit).
- `single_values._cost_of_debt_point`: on a year no interest caveat covers, `_stated_rate_note`:
  - At each of the year's two year ends (the dates of the opening and closing debt D8 averaged), the stated rate dated exactly then, the newest filing's version known on the run's date. The short-term rate goes on the debt Warren counted there that `short_rate_covers` names (`short_term_borrowings` and `commercial_paper`, plus `debt_current` and `debt_current_total` for `due_within_one_year`), the long-term rate on the rest; with no short-term rate, the long-term rate on all of it.
  - The stated rate is the mean of the two year ends' blends, or the closing one alone when the opening has no rate (a flow over the year against year-end rates, analyst B1). No closing rate: no check.
  - When |cost of debt − stated| > `STATED_RATE_GAP` (0.01, one percentage point, a Warren working rule): point note `far_from_stated_rate`, params `fiscal_year`, `cost_of_debt` (the run's own row on the used year, as `below_risk_free` and the hedge note compare), `stated_rate`, `gap` (signed: cost of debt − stated rate, below zero when the book rate is lower), `threshold`, `short_rate_covers` (None when the long-term rate stood for all the debt), `year_ends` (oldest first: `period_end`, `stated_rate`, `long_term_rate`, `short_term_rate`, `short_term_share` as a fraction of that year end's debt, `long_term_rate_filing` and `short_term_rate_filing` in the #140 filing shape `{accession_no, form, filed_at, url, filer}` for the *Fuente* link).
  - Never on a year an interest caveat covers: `interest_net_of_hedge_gains` already sets the book rate beside the stated one, with the cause (product lead, blocker 1). It can sit beside `below_risk_free` on one point (after it).
  - The `cost_of_debt` cell carries the used year's note, as it does the hedge note (never both, since they never share a year).
- `reading_rules.md`: a row under version 15 (`blended_rate` is in a rules module but no run calls it).
- Tests: `tests/analysis/test_stated_debt_rate.py` (16: within and beyond the gap, both signs, two year ends averaged and the closing alone, each `short_rate_covers` blend by hand, the long-term rate for all with no short-term item, no note without a closing rate, a rate filed after the run's date never read, a caveat year gets the hedge note only, the cell, the closed lists, no number moves), `tests/analysis/test_stated_debt_rates.py` (9, the loader), the `blended_rate` properties, `tests/fundamentals/test_concepts.py` (the reported-only items and their scope). The test fixture now files any tag ending in `InterestRate` as a ratio, so the tests use the real tags.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot (`warren-20261125T103202Z`): `reproduce --all` and `--rebuild` before; `fundamentals ingest --all` (only KO and PG should gain facts); `fundamentals report --all`; `reproduce --all` and `--rebuild` after, with as many identical rebuilds as before. Then every stored KO, PG and JNJ run's own cost-of-debt year through `cost_of_debt_notes`, and each company's newest run's chart. Exit: no stored run changes; the note on Coca-Cola's FY2020 and FY2021 only; J&J's covered years keep their hedge note alone. Save a snapshot.

## Results (Step 2, nov.26.2026)

On the restored snapshot `warren-20261125T103202Z`.

- **Before anything changed** (main at `96ac329`): `reproduce --all`: 936 of 936 stored runs reproduced to the cent; `--rebuild`: 723 of 936 rebuilt to identical rows.
- **Ingest.** Coca-Cola gains 50 facts and P&G 62 (the two rates, every 10-K's version); no other company gains any. `fundamentals report --all`: 0 unexplained gaps for all eight companies.
- **After the ingest.** 936 of 936 reproduced to the cent; 723 of 936 rebuilt to identical rows, the same as before.
- **The check on every stored run's own year** (gap = cost of debt − stated rate, in points):

| Company | FY (runs) | Gap | Note |
|---|---|---|---|
| KO | 2018 (15), 2019 (13) | +0.12, +0.20 | no |
| KO | **2020 (16)** | **+1.60** (3.36% against 1.76%, both year ends) | **yes** |
| KO | **2021 (14)** | **+2.15** (3.73% against 1.58%) | **yes** |
| KO | 2022 to 2025 (57) | +0.16 to +0.77 | no |
| PG | 2018 to 2026 (115) | −0.70 to +0.54 | no |
| JNJ | 2018 to 2025 (115) | | no: every run's year is one the hedge caveat covers, so its note stays alone |

  On the newest runs' charts the same: Coca-Cola's FY2020 and FY2021 points only; P&G none; J&J FY2017 (the one uncovered year in its window) none. The largest quiet gap is Coca-Cola FY2023's +0.77, a year its stated short-term rate rose from 4.2% to 5.3% and its year-end rates sit above the year's average; the two firing years are at least 0.8 points beyond the line.
- No stored run, row or number changes: the note is built when an answer is read, not stored.

## Alternatives considered

- **A run note in `math_engine` (the first draft).** The issue asked for one, but J&J's covered years would then carry two notes quoting the same stated rate with two causes (product lead, blocker 1), the check would change the valuation map's fingerprint for a figure no valuation reads, and the chart would still lack it per year. The chart and cell are where the hedge note already lives. Changed.
- **Use the stated rate as the cost of debt.** It changes D8's method (an M2 decision, `docs/build-plan.md` line 196; an owner card), only three companies state it, it is a year-end rate, and it is not the market cost of new borrowing either (professor; Koller et al., *Valuation*, 7th ed., the cost of capital chapter). Rejected; the note is the evidence a later card would need.
- **The short-term rate on short-term borrowings and commercial paper for every company (the first draft).** P&G's note puts its short-term rate on all debt due within one year, current portion included (analyst B1), so the split is per company, in the data file.
- **The closing year end alone (the first draft).** In a year rates rise, year-end rates sit above the year's average: P&G FY2023 came to −0.997 points, 0.003 from firing, with the right split (analyst). Averaging both ends brings it to −0.25.
- **Compare with the long-term rate alone.** P&G and Coca-Cola hold 10% to 37% of their debt as commercial paper at much lower rates. Rejected.
- **A gap relative to the stated rate.** At low rates a ratio fires on small absolute gaps; an analyst reads a cost of debt in points. Rejected.
- **Take Coca-Cola's charges out of its interest.** The right fix for its FY2020 and FY2021 D8, but it changes which figures a run reads; a follow-up issue, with the note's evidence.

## Files to change

`domains/fundamentals/concept_map_reported.csv`, `domains/analysis/stated_debt_rates.csv` (new), `domains/analysis/stated_debt_rates.py` (new), `domains/analysis/financial_math.py`, `domains/analysis/single_values.py`, `domains/analysis/reading_rules.md`, `tests/analysis/test_stated_debt_rate.py` (new), `tests/analysis/test_stated_debt_rates.py` (new), `tests/analysis/test_financial_math_properties.py`, `tests/analysis/conftest.py`, `tests/fundamentals/test_concepts.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`. `docs/structure-guide.md` and `docs/build-plan.md` are unchanged (no milestone, no decision).

## Product impact

Serves brief Q5 (every input behind an answer, the cost-of-debt chart) and the `cost_of_debt` cell on Q3, Q4 and Q8's screens. One new code, `far_from_stated_rate`, in `single_values.POINT_NOTES` and `CELL_NOTES`; nothing renamed or removed; no number changes.

- **Where it shows.** On a cost-of-debt point after `below_risk_free` when both are there, and on the `cost_of_debt` cell for the run's own year. Never with `interest_net_of_hedge_gains` (they never share a year).
- **Params for the Spanish.** `gap`'s sign picks "por encima" or "por debajo"; `stated_rate`, `cost_of_debt` and `threshold` are fractions; each `year_ends` entry gives the date, the long-term and short-term rates (`short_term_rate` None: none stated, or no short-term debt that year end), and `short_term_share` as a fraction of that year end's debt ("el {x} % de su deuda vencía en el año"). `short_rate_covers` None means the long-term rate stood for all the debt; `short_term_borrowings` and `due_within_one_year` say which debt the short-term rate was on.
- **Source link.** `long_term_rate_filing` and `short_term_rate_filing` are full filing objects, as the hedge note's `effective_rate_filing` (blocker 2).
- **The app needs** a Spanish title, a sentence from the params, a short lesson (a book cost of debt moves with anything booked on the interest line, such as hedge gains or charges for repaying debt early; the company's own rate is a check, not the rate a valuation would ideally use, which is the market cost of new borrowing; the one point is Warren's working rule from three companies' history), and its catalogue line.
- **Today** it appears on Coca-Cola's FY2020 and FY2021 points, and on the cell of the 30 Coca-Cola runs whose own year is one of them.

## Design review (nov.26.2026)

- **Analyst, NO-GO on the first draft, one blocker, taken.** B1: P&G's short-term rate covers all its debt due within one year, current portion included, and with that split the closing year end alone left P&G FY2023 0.003 points from firing; fixed with a per-company split in data and the mean of both year ends. Confirmed: Coca-Cola's charges in interest expense (0000021344-22-000009), what each rate covers, no restated rates, the `pure` unit. Taken: reuse the debt facts D8 counted (S2); rounding in the threshold's reason (S1). Noted: J&J's long-term rate on its paper biases its stated rate up (in the data file's evidence); P&G books its FY2021 extinguishment charge outside interest, so the lesson says "can", not "does" (S3).
- **Professor, GO.** Taken: the lesson should say neither rate is the market cost of new borrowing (Koller et al.; Damodaran), that the one point comes from three companies' history, and the year-end against year-average timing (now handled by averaging both ends). J&J's swaps as synthetic foreign-currency debt are the hedge note's job, which this note never replaces. Idea for the app: a book, stated and market rate side by side (outside Phase 1).
- **Product lead, NO-GO on the first draft, two blockers, taken.** J&J would have had two notes quoting one rate: the check moved to the chart and never runs on a caveat year. A full filing object for the source link. Gaps taken: `gap`'s sign, the note's position, the cell, `short_term_share`'s base.
- **Explainer, 14 gaps.** Answered above: which year ends and dates (the debt D8 averaged), the long-term part (the rest of the counted debt), missing inputs (no closing rate, no note; debt not above zero, no year end), the run's date for point-in-time, the newest filing's version, the sign and units, the confirmed Coca-Cola cause, the `short_term_share` base. The map-copy question no longer applies (the reported-only file has no copies).

## Follow-ups

- Coca-Cola FY2020 and FY2021: take the early-extinguishment charges out of interest in D8 (it changes which figures a run reads).

## Where the work stopped

Steps 0 to 2 built; PR, gatekeeper and merge next.
