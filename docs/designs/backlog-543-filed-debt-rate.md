# Backlog #543: flag a cost of debt far from the company's own filed rate on its debt

Issue: https://github.com/sonderbot-ar/warren/issues/543 (item 3 of #540, from the #533 analyst) · Branch `backlog-543-filed-debt-rate` · Version v0.10.53 when merged.

Status: In progress (nov.26.2026).

## Problem

Warren's cost of debt (D8, `docs/build-plan.md` line 196) is a fiscal year's interest over the average of its two year-end debts (`math_engine.cost_of_debt_year`). It is a book figure, and it can be far from what the company actually pays on its borrowing when the interest line holds something other than interest on the debt. Two cases are in Warren's data today:

- **J&J FY2019 to FY2022**: the interest line is net of about half a billion dollars a year of cross-currency swap gains (#540, #542), so D8 reads 0.67% to 1.33% while J&J's own weighted average effective rate on its long-term debt is 2.85% to 3.19%.
- **Coca-Cola FY2020 and FY2021**: D8 reads 3.36% and 3.73% while Coca-Cola's filed weighted average rates on its debt are about 1.6% (to be confirmed by the analyst: the 10-Ks book charges for the early extinguishment of long-term debt inside interest expense).

Nothing tells a reader of the run. Warren already warns when D8 is outside 0% to 15% (`cost_of_debt_out_of_bounds`), but both cases are inside that band. Three companies file, in their debt note, the rate they pay on average, as a tag without a dimension, so Warren can read it point-in-time like any fact:

| Company | Long-term rate (year end) | Short-term rate (year end) |
|---|---|---|
| Coca-Cola | `LongtermDebtWeightedAverageInterestRate`, FY2016 on | `ShortTermDebtWeightedAverageInterestRate`, FY2009 on |
| P&G | `LongtermDebtWeightedAverageInterestRate`, FY2014 on | `ShortTermDebtWeightedAverageInterestRate`, FY2009 on |
| J&J | `DebtInstrumentInterestRateEffectivePercentage` (weighted average effective rate on long-term debt), FY2011 to FY2024; FY2025 not tagged | none |

Apple, Walmart and Exxon file only a short-term rate (Exxon's long-term 3.43% is tagged only with a dimension, which company facts leave out); Microsoft and Caterpillar file neither. (Company facts, nov.26.2026.)

This item adds a check, not a new method: D8's value does not change on any run. When the company files a rate, the run says how far D8 is from it, and warns when the gap is large.

### What the check gives on today's data (fiscal years from FY2014, the run's newest-year rule, in memory)

The filed rate is blended by the debt Warren counts at the cost-of-debt year's closing date: the short-term rate on the short-term borrowings and commercial paper, the long-term rate on the rest (the current and non-current portions of long-term debt, and any finance leases). Where the company files no short-term rate (J&J), the long-term rate stands for all of it, and the note says so.

| Company | FY | D8 | Long-term | Short-term | Short-term share | Filed (blend) | Gap |
|---|---|---|---|---|---|---|---|
| KO | 2016–2019 | 1.64%–2.18% | 1.7%–1.9% | 0.8%–2.6% | 26%–31% | 1.46%–2.12% | −0.05 to +0.25 |
| KO | 2020 | 3.36% | 1.6% | 1.3% | 5% | 1.58% | **+1.77** |
| KO | 2021 | 3.73% | 1.7% | 0.1% | 8% | 1.58% | **+2.16** |
| KO | 2022–2025 | 2.15%–3.83% | 2.3%–3.4% | 3.9%–5.3% | 3%–11% | 2.42%–3.61% | −0.26 to +0.37 |
| PG | 2014–2026 | 1.38%–2.76% | 2.0%–3.3% | 0.2%–4.2% | 10%–37% | 1.70%–3.30% | −0.85 to −0.20 |
| JNJ | 2014–2018 | 3.33%–3.52% | 3.19%–4.08% | none | 9%–35% | 3.19%–4.08% | −0.71 to +0.19 |
| JNJ | 2019 | 1.33% | 3.19% | none | 4% | 3.19% | **−1.86** |
| JNJ | 2020 | 0.84% | 2.85% | none | 7% | 2.85% | **−2.01** |
| JNJ | 2021 | 0.67% | 2.89% | none | 11% | 2.89% | **−2.22** |
| JNJ | 2022 | 0.89% | 3.04% | none | 32% | 3.04% | **−2.15** |
| JNJ | 2023, 2024 | 2.44%, 2.53% | 2.98%, 3.36% | none | 12%, 16% | 2.98%, 3.36% | −0.54, −0.83 |
| JNJ | 2025 | 2.57% | not tagged | none | | | no check |

(D8 through today's map on the nov.25 snapshot, as known on 2026-11-20; rates from company facts, the first 10-K that filed each year end.)

A gap of more than one percentage point separates the two known causes (J&J's swaps, Coca-Cola's charges) from the ordinary difference between a year-end rate and a year's average one: P&G's largest gap is −0.85 points in FY2023, a year when rates rose about four points, so its year-end rates sit above the year's average.

## Plan

**Step 0. This doc.**

**Step 1. The filed rates in the map, and the note.**

- Map (`domains/fundamentals/concept_map.csv`): two optional items, unit `pure`, period type `instant`.
  - `debt_rate_long_term`: `us-gaap:LongtermDebtWeightedAverageInterestRate` priority 1 (KO, PG), `us-gaap:DebtInstrumentInterestRateEffectivePercentage` priority 2, limited to JNJ (a generic tag another company may use per instrument; J&J's undimensioned fact is the weighted average effective rate on its long-term debt). Priority 1 limited to KO and PG too, since the loader needs every row of an item limited when one is.
  - `debt_rate_short_term`: `us-gaap:ShortTermDebtWeightedAverageInterestRate`, limited to KO and PG (the only companies with a long-term rate to blend it with; Apple's, Walmart's and Exxon's would never be used).
  - Notes cite the filings. Map copy `concept_maps/<sha>.csv` and its `CHANGES.md` line.
- Engine (`math_engine.py`): `FILED_RATE_ITEMS` read like the check items (only when the map in force has them, so a rebuild through an older map reads what it read). A new `FILED_RATE_GAP = 0.01` (one percentage point, a Warren working rule). After `_cost_of_debt` adds the row, `_filed_rate_note(history, year, kd, end, end_used, result)`:
  - reads the cost-of-debt year's long-term rate (`history.year(year)`); none: no check, no note.
  - short-term part = the closing debt's `short_term_borrowings` and `commercial_paper` facts above zero; rate = the year's short-term rate, or the long-term rate when none is filed (`short_term_rate` None in params).
  - filed = (long-term rate × (closing debt − short-term part) + short-term rate × short-term part) / closing debt, through `financial_math` (a new `blended_rate`, with property tests).
  - When |D8 − filed| > `FILED_RATE_GAP`: run note `cost_of_debt_far_from_filed_rate` (group `assumption`), params `{cost_of_debt, filed_rate, gap, threshold, fiscal_year, period_end, long_term_rate, short_term_rate, short_term_share, accession_no}` (rates and shares as fractions, `accession_no` the long-term rate's filing), English text "Cost of debt X% is Y points above/below the company's own filed rate on its debt (Z%, FY…)".
  - The check never changes D8, WACC or any number.
- `coded.RUN_NOTE_CODES` gains the code; `text.WARNING_LESSONS` gains its lesson (two sentences: a cost of debt from the income statement can hold things other than interest on the debt, such as hedge gains or charges for repaying debt early; the company's own rate is a check on it; the one point is a working rule), with `{threshold}` from the constant.
- `reading_rules.md`: a row under version 15 (the note changes no figure a run reads, so the version stays).
- Tests: `tests/analysis/test_filed_debt_rate.py` (new): a Test Corp fixture with a filed long-term rate that warns above the gap, stays silent within it, blends a short-term rate, uses the long-term rate for all when no short-term rate is filed (and says so), gives no note without a long-term rate, reads no rate filed after the run's date (point-in-time), and leaves every assumption row identical with and without the rates; `tests/analysis/test_warning_lessons.py` threshold table; `tests/fundamentals/test_concepts.py` and `test_ingest.py` for the map's scope; property tests for `blended_rate` in the `financial_math` suite (between its two rates, equal to the long-term rate at share 0, the short-term at share 1).
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot (`warren-20261125T103202Z`): `reproduce --all` and `--rebuild` before; `fundamentals ingest --all` (only KO, PG and JNJ should gain facts, the rates); `fundamentals report --all` (no new unexplained gaps; the items are optional); `reproduce --all` and `--rebuild` after, with as many identical rebuilds as before. Then every stored run date built fresh in memory through main's map and the new one; none stored. Exit: no assumption row moves on any run; the note appears only on the KO, JNJ runs whose cost-of-debt year is in the table's bold rows, listed by year. Save a snapshot.

## Alternatives considered

- **Use the filed rate as the cost of debt.** Closer to what the company pays, but it changes D8's method (an M2 decision, `docs/build-plan.md` line 196; an owner card), only three companies file it, and it is a year-end rate. Rejected for this item; the note gives the evidence a later card would need.
- **Compare with the long-term rate alone.** Simpler, but P&G and Coca-Cola carry 10% to 37% of their debt as commercial paper at much lower rates, so P&G would warn in four of its thirteen years (FY2014 to FY2017, gaps −1.08 to −1.30 points) for no reason. Rejected.
- **A gap relative to the filed rate (for example D8 outside half to twice it).** At today's low rates a ratio fires on small absolute gaps (P&G FY2017: 1.50% against 1.82%), and an analyst reads a cost of debt in points. Rejected.
- **Average the opening and closing filed rates.** Closer to the year's average, but the opening rate is a year older and J&J's first year would have none; the gap would barely move (P&G FY2023 −0.85 → about −0.5). Left for the review to weigh.
- **Put the check on the cost-of-debt chart's every year too** (`single_values`). Useful for brief Q5's chart, but a second place for one rule; a follow-up once the run note settles.

## Files to change

`domains/fundamentals/concept_map.csv`, `domains/fundamentals/concept_maps/<sha>.csv` and `CHANGES.md`, `domains/analysis/financial_math.py`, `domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.md`, `tests/analysis/test_filed_debt_rate.py`, `tests/analysis/test_warning_lessons.py`, `tests/analysis/test_financial_math*.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`. `docs/structure-guide.md` and `docs/build-plan.md` are unchanged (no milestone, no decision: D8's method is the same).

## Product impact

Serves brief Q3, Q4 and Q5 (a value per share, the WACC and its parts, every input behind an answer): a run of Coca-Cola or J&J whose cost-of-debt year is far from the company's filed rate gets one new run note, `cost_of_debt_far_from_filed_rate`, group `assumption`, with its lesson, ranked like `cost_of_debt_out_of_bounds` and pointing at the `cost_of_debt` row. Params are raw (fractions for rates, gap and share; `short_term_rate` null when the long-term rate stood for all the debt; `accession_no` for a *Fuente* link through the #140 filing shape the app already builds). The app needs a Spanish title, sentence and lesson for it, and a catalogue line. No number on any run changes; no output is renamed or removed. Stored runs keep their notes: a fresh run beside a stored one of the same date shows the note only on the new one, under the same reading rules (15) but a different map fingerprint (brief "different map fingerprints" case).

## Where the work stopped

Step 0 written; design review next.
