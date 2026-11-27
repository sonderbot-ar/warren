# Backlog #610: Coca-Cola's cost of debt leaves out the charges for paying debt off early

Issue: https://github.com/sonderbot-ar/warren/issues/610 (from the #543 analyst review, PR #609) · Branch `backlog-610-ko-extinguishment` · Version v0.10.54 when merged.

Status: In progress (nov.27.2026).

## Problem

Warren's cost of debt (D8, `docs/build-plan.md` line 214) is a fiscal year's interest over the average of its two year-end debts (`math_engine.cost_of_debt_year`). Coca-Cola books the gain or loss on paying debt off before maturity inside its interest expense line, so in the years it buys back bonds early the line is not the interest on its debt. In FY2020 and FY2021 the charges were large (459M and 559M), and D8 reads 3.36% and 3.73% while Coca-Cola's own debt table states about 1.6% to 1.8%; v0.10.53's `far_from_stated_rate` note fires on both years (+1.60 and +2.15 points).

**Where Coca-Cola books it.** Every 10-K says so in words, for every year it happened (checked in each filing's text, nov.27.2026):

| FY | Filed text | Tagged `GainsLossesOnExtinguishmentOfDebt` (10-K, annual) | Interest expense |
|---|---|---|---|
| 2013 | "associated charges of $53 million ... in the line item interest expense" (FY2015 10-K, 0000021344-16-000050) | none (only in two 10-Qs, year to date, −23M) | 463 |
| 2015 | "charges of $320 million that were recorded in the line item interest expense" (0000021344-16-000050) | −320 (0000021344-16-000050) | 856 |
| 2016 | none: the FY2016 10-K's text names only 2015's $320M (0000021344-17-000009) | **−320, a context error** (0000021344-17-000009) | 733 |
| 2017 | "a net charge of $38 million that was recorded in the line item interest expense" (0000021344-18-000008) | −38 | 853 |
| 2018 | "a net gain of $27 million in the line item interest expense ... during the year ended December 31, 2018" (0000021344-19-000014) | +27 | 950 |
| 2019 | none: the FY2019 10-K says "prior year interest expense included a net gain of $27 million" (0000021344-20-000006); the FY2020 10-K's text puts the gain in 2018 (0000021344-21-000008) | **+27, a context error** (0000021344-21-000008, FY2020 10-K) | 946 |
| 2020 | "charges of $459 million recorded in the line item interest expense" (0000021344-22-000009, Note 10); Item 7 total 484M | −459 | 1,437 |
| 2021 | "charges of $559 million recorded in the line item interest expense" (0000021344-22-000009, Note 10); Item 7 total 650M | −559 | 1,597 |
| 2024 | "a gain of $22 million recorded in the line item interest expense" (0000021344-25-000011) | +22 | 1,656 |

(Millions of US$; the tag's sign is a gain, so a charge is negative.) The tag sits without a dimension and, in every year it is right, equals the amount the text says was recorded in interest expense. Two 10-Ks put the year before's figure under their own year's dates (FY2016's 10-K the 2015 charge, FY2020's 10-K the 2018 gain); in each the same filing's text says which year it was, so the error is visible on the day it was filed, not only with hindsight. The Item 7 totals for 2020 and 2021 add 25M and 91M of cash-flow hedge losses moved out of other comprehensive income ("charges of $91 million as a result of the reclassification of related cash flow hedging balances from AOCI into income", FY2021 10-K); those are not tagged apart and stay in the interest.

**What it does to D8** (today's map and code, as known on 2026-10-30; average debt in millions):

| FY | Average debt | Interest | Today | Without the tagged figure |
|---|---|---|---|---|
| 2015 | 42,824 | 856 | 2.00% | 1.25% (536) |
| 2017 | 46,613 | 853 | 1.83% | 1.75% (815) |
| 2018 | 45,950 | 950 | 2.07% | 2.13% (977) |
| 2020 | 42,778 | 1,437 | 3.36% | 2.29% (978) |
| 2021 | 42,777 | 1,597 | 3.73% | 2.43% (1,038) |
| 2024 | 43,293 | 1,656 | 3.83% | 3.88% (1,678) |

FY2016 and FY2019 do not move (the context errors are left out). FY2021 still reads about 0.6 points over the stated rate: the 91M hedge reclass and the stated rate being a year-end coupon, not the year's average, explain the rest.

## Plan

**Step 0. This doc.**

**Step 1. Coca-Cola's interest leaves out the gain or loss on paying debt off early.**

- New optional map item `debt_extinguishment_in_interest`: `us-gaap:GainsLossesOnExtinguishmentOfDebt`, priority 1, duration, USD, `companies=KO`. Note: Coca-Cola records the gain or loss on extinguishing debt early in its interest expense line (every 10-K's text, 2013 to 2024), so its cost of debt takes it out. Scoped to KO: other companies book the same tag in other income (P&G's FY2021 charge, #610) or not at all, so each must be checked first.
- New data file `domains/analysis/misdated_facts.csv` (Decision 11, companies as data), columns `ticker, canonical_name, fiscal_year, accession_no, evidence`: one row per filed fact a filing put under the wrong year, with the filing's own words that say so. Two rows today, KO's FY2016 (0000021344-17-000009) and FY2019 (0000021344-21-000008). A loader validates every row at once (ticker in `universe.csv`, item one of the optional interest items D8 reads, an accession whose filer prefix is the company's CIK, evidence that names the accession) and the engine reads it once.
- `math_engine.d8_interest` gains a step inside `_incurred`, before the non-debt and capitalised parts: the interest less the extinguishment figure's loss (plus its gain): `interest − (−value)`. Left out, with the figure's trace in the method, when its fact is listed in `misdated_facts.csv` (no older version stands in: those years had no extinguishment), or when taking it out would leave the interest at or below zero. Method text: `<resolved method> - gain or loss on early extinguishment of debt (recorded in interest expense): <trace>`; facts are the interest's plus the one used, so the row's sources and the chart's parts cite it. Never on the cash `interest_paid` fallback. Microsoft's cash path and Walmart's lease step unchanged.
- `debt_extinguishment_in_interest` joins `OPTIONAL_ITEMS`, so a rebuild through an older map reads what it read.
- Map copy `concept_maps/<sha>.csv`, its `CHANGES.md` line, a `reading_rules.md` row: `READING_RULES_VERSION` 15 → 16.
- Tests (`tests/analysis/test_extinguishment_interest.py`, `tests/fundamentals/test_concepts.py`): the shipped map loads with the scoped row; Coca-Cola's FY2021 figures give (1,597 − 559) / 42,777; a gain adds back (FY2018); a listed fact is left out and the method says why; a figure that would take the interest to zero or below is left out; never on the `interest_paid` fallback; Exxon's #533, J&J's #540, Microsoft's #527 and Walmart's #497 cases unchanged; the data file's loader refuses each bad row and the shipped file loads.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot (`warren-20261126T202919Z`): `fundamentals ingest --all` (only Coca-Cola should gain facts); `fundamentals report --all`; `reproduce --all` to the cent, and `reproduce --all --rebuild` with as many runs rebuilding to identical rows after the ingest as before. Then every stored run date built fresh in memory through main's map and code and the new ones, pinned market data and choices, none stored; list cost of debt, WACC, value per share and the cost-of-debt chart's `far_from_stated_rate` and `below_risk_free` by year. Exit: only Coca-Cola moves, only its `cost_of_debt` row and what follows from it, and only on runs whose own year is FY2015, 2017, 2018, 2020, 2021 or 2024. Save a snapshot.

## Alternatives considered

- **Take the Item 7 totals (484M, 650M).** Closer to the stated rate in FY2021, but the extra 25M and 91M are not tagged; transcribing them by hand into a data file is the first number Warren would not read from a filing's XBRL. Left in, said in the lesson.
- **A rule instead of a list for the two context errors** (for example, count the figure only when the year's own 10-K reports it). It catches FY2019 but not FY2016, whose own 10-K is the one that misdated the 2015 charge. A listed error with the filing's own words is plainer and testable.
- **Fix the context errors in the facts layer for every item.** Wider than the issue: every reader of the fact would change. A follow-up if another item ever needs it.
- **A note only.** Leaves a number Warren knows is wrong when a filed figure fixes it.

## Files to change

`domains/fundamentals/concept_map.csv`, `domains/fundamentals/concept_maps/<sha>.csv` and `CHANGES.md`, `domains/analysis/math_engine.py`, new `domains/analysis/misdated_facts.csv` and `domains/analysis/misdated_facts.py`, `domains/analysis/reading_rules.md`, `domains/analysis/reading_rules.py` (version 16), new `tests/analysis/test_extinguishment_interest.py`, `tests/fundamentals/test_concepts.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` unchanged (backlog item). `docs/structure-guide.md` is unchanged: D8's method (interest over average book debt) is the same, only which filed lines make up a company's interest, as in #497, #527, #533 and #540, so no decision changes and no owner card is needed.

## Product impact

Coca-Cola appears in any company screen of the Q3, Q4, Q5, Q7, Q8 and Q9 kind (`docs/product/brief.md`: value per share, WACC and its parts, the inputs behind an answer, a rate shock, a margin what-if, the sensitivity grid). A fresh Coca-Cola run whose own cost-of-debt year is FY2015, 2017, 2018, 2020, 2021 or 2024 reads a different cost of debt (FY2021 2.43% instead of 3.73%): a slightly lower WACC and a slightly higher value per share (Step 2 gives the numbers). The cost-of-debt chart's points for those years move the same way, and `far_from_stated_rate` should stop firing on FY2020 and may still fire on FY2021 (Step 2 lists it). The chart's parts gain one part code, `debt_extinguishment_in_interest`. Its `value` is the figure as filed, with its sign: negative for a loss (FY2021: −559M), positive for a gain (FY2018: +27M), and the year's interest is the expense plus it, so the app shows the sign it is given and never works it out (product lead). Spanish, proposed by the product lead and checked by the student reviewer on the front-end's side: label "Pérdida o ganancia por cancelar deuda antes de tiempo"; *Fuente* "{empresa} registra dentro de su gasto por intereses la pérdida o ganancia por cancelar deuda antes de su vencimiento. No es interés de su deuda, así que Warren la saca del costo de la deuda." The brief's reading-rules count moves to 16. Stored runs keep their rows; beside a fresh run they differ by reading rules (brief line 107) or, with no recorded rules, the "either NULL" case (line 108). No field, code or output is renamed or removed.

## Design review (nov.27.2026)

- **Analyst, GO, no blockers.** Checked on EDGAR: the tag equals the amount the text says was recorded in interest expense in every year kept (FY2015, 2017, 2018, 2020, 2021, 2024); both context errors confirmed in the filings' own words; no new extinguishment in the FY2022, FY2023 or FY2025 10-Ks; interest on tax liabilities sits in income taxes, not in the line. Taken into the text: the stored interest for FY2017 and FY2018 differs by as-of date (the FY2019 10-K restated 841 → 853 and 919 → 950 when a bottler stopped being a discontinued operation), so Step 2 lists the interest each run actually read; the swap settlements inside Coca-Cola's interest line are a real cost of its debt and go in the lesson as the reason FY2021 still reads 0.6 points over the stated rate. Ideas filed as one backlog issue: a warning when a year's figure equals the year before's as filed (the shape of both errors), and caveat rows for FY2013's untagged 53M and the untagged hedge reclass (25M, 91M).
- **Professor, GO, no blockers.** ASC 470-50-40-2 (the difference is recognised in the period of extinguishment), IFRS 9 3.3.3, and Koller et al. and Damodaran's yield-based cost of debt support taking a one-off out of a book-rate proxy; the list of misdated facts is sound because each error shows in the same filing. Taken into the lesson: part of a loss is unamortised issue cost and discount written off early, interest pulled forward, so removing the whole figure slightly understates the historic rate; the hedge reclass stays only because it is not tagged; FY2013's charge is not removed and says so.
- **Explainer.** Seventeen gaps; taken: `fiscal_year` in the data file is the year the filing's dates give the fact (the wrong year); "left out" means the figure is not used and the year keeps its interest; the zero check is on the adjusted interest; a bad row fails the whole file with every problem listed; `interest − (−value)` is written as `interest + value`; FY2013 is excluded because it has no annual tag. The rest are defined in the files the doc links (map priority and `companies`, the earlier cases, the brief lines).
- **Product lead, GO.** Two changes taken: the label is a capitalised noun phrase like the others, and the doc says the part's value carries its sign (above); the Spanish *Fuente* sentence is theirs.
