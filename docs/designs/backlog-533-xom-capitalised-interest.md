# Backlog #533: ExxonMobil's cost of debt counts the interest it capitalises

Issue: https://github.com/sonderbot-ar/warren/issues/533 (from the #527 analyst review) · Branch `backlog-533-xom-capitalised-interest` · Version v0.10.33 when merged.

Status: In progress (Step 1 built; Step 2, real data, next).

## Problem

Warren's cost of debt (D8, `docs/build-plan.md` line 214) is a fiscal year's interest over the average of its two year-end debts (`math_engine.cost_of_debt_year`). For ExxonMobil the interest is the income statement's `us-gaap:InterestExpense`, which is net of the interest Exxon capitalises into projects under construction (ASC 835-20; the FY2025 10-K's accounting policy limits it to "interest costs incurred to finance expenditures during the construction phase of multiyear projects", analyst) and holds some interest that is not on debt (below). Exxon capitalised between 46% (FY2018) and 72% (FY2025) of its interest, so the line has fallen while its debt has not. The newest stored run, `XOM_2026-10-30_2`, reads 1.41% (603M over average debt 42,624M), well below FY2025's average 10-year Treasury yield and the run's risk-free rate.

**What Exxon files.** Unlike Microsoft (#527), Exxon tags the capitalised amount itself, every year (company facts, nov.22.2026):

| FY | Interest expense (`InterestExpense`) | Capitalised (`InterestCostsCapitalized` to FY2020; `InterestPaidCapitalized` FY2017 on) | Cash paid (`InterestPaid`) | Cash paid, net (`InterestPaidNet`) |
|---|---|---|---|---|
| 2017 | 601 | 749 | 1,132 | 383 |
| 2018 | 766 | 652 | 955 | 303 |
| 2019 | 830 | 731 | 1,291 | 560 |
| 2020 | 1,158 | 665 | 1,451 | 786 |
| 2021 | 947 | 655 | 1,474 | 819 |
| 2022 | 798 | 838 | 1,504 | 666 |
| 2023 | 849 | 1,152 | 1,736 | 584 |
| 2024 | 996 | 1,276 | 1,900 | 624 |
| 2025 | 603 | 1,534 | 1,752 | 218 |

(Millions of US$, 10-K annual figures; FY2025 from accession 0000034088-26-000045.) In the four years both capitalised tags are filed (FY2017 to FY2020) they are equal, so they are one figure: `InterestCostsCapitalized` ("interest capitalized during the period") in the 10-Ks to FY2020 (FY2017 in 0000034088-18-000015), `InterestPaidCapitalized` ("cash paid for interest capitalized") in the cash-flow statement from the FY2019 10-K on (FY2017 first in 0000034088-20-000016). Cash paid = net + capitalised in every year, as the tags say.

**Basis.** Exxon's debt in Warren counts finance leases: its long-term tag is `LongTermDebtAndCapitalLeaseObligations` (the run's debt note: "finance leases skipped: the debt tag already includes them"; the 10-K's long-term debt table lists "Finance leases & other obligations", 6,313M at 2025-12-31), and Exxon files no separate finance-lease interest, so lease interest sits inside the expense and lease debt and lease interest match (analyst). **But the expense also holds interest that is not on debt** (analyst, blocker taken): the FY2025 10-K's segment note, Corporate and Financing, says "Interest expense includes non-debt-related interest expense of $0.3 billion in 2025, $0.4 billion in 2024, and $0.2 billion in 2023", tagged `us-gaap:InterestExpenseOther` in every 10-K (FY2017 to FY2022: 136, 84, 105, 148, 103, 117M; FY2023 234M restated to 200M; FY2024 437M restated to 400M; FY2025 300M; FY2013 −123M). So interest on debt is expense − not on debt. Capitalised interest is interest on that same debt, moved into an asset's cost. So **interest expense − interest not on debt + interest capitalised = interest incurred on debt**, the textbook figure (ASC 835-20-30; Kieso, Weygandt and Warfield, *Intermediate Accounting*, ch. 10), on the same basis as the debt. Commercial paper is not a problem here (it was for #527's cash figure): the expense accrues the paper's discount, and the capitalised part is a share of interest incurred, paper included.

Interest incurred on debt over average debt, read through today's map as known on 2026-10-30 (`load_history`, in memory; non-debt rows from the analyst):

| FY | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| Average debt (M) | 39,413 | 42,358 | 57,280 | 57,672 | 44,448 | 41,383 | 41,642 | 42,624 |
| Today (expense) | 1.94% | 1.96% | 2.02% | 1.64% | 1.80% | 2.05% | 2.39% | 1.41% |
| Expense + capitalised (first draft) | 3.60% | 3.69% | 3.18% | 2.78% | 3.68% | 4.84% | 5.46% | 5.01% |
| New: − not on debt + capitalised | 3.38% | 3.44% | 2.92% | 2.60% | 3.42% | 4.35% | 4.50% | 4.31% |

Against the 10-K's own debt table (analyst): the average effective rates at 2025-12-31, weighted by balance, are 3.43% on 34.3B of long-term debt and 3.8% on short-term borrowings, so a book rate near 4.3% for FY2025 is plausible and the first draft's 5.0% to 5.5% was not. A book rate is not compared with the year's Treasury yield as a test: it lags market rates (Exxon's low-coupon 2020 notes sit below the 2023 to 2025 yields), so `below_risk_free` firing on a book rate is a note, not a sign of an error (analyst). Stored Exxon runs keep their rows; runs built before #412 also read a smaller FY2018 and FY2019 debt (without commercial paper); Step 2's fresh builds read today's debt.

## Plan

**Step 0. This doc.**

**Step 1. Exxon's cost of debt adds the interest it capitalises.**

- New optional map item `interest_capitalized`: `us-gaap:InterestPaidCapitalized` priority 1 and `us-gaap:InterestCostsCapitalized` priority 2 (the map's priority: where both are filed for a period the first wins; they are equal there, and before FY2019's 10-K only the second is public), duration, USD, `companies=XOM`. New optional map item `interest_not_on_debt`: `us-gaap:InterestExpenseOther`, priority 1, `companies=XOM` (analyst). Each figure is read as known on the run's date, so FY2023 and FY2024's restated non-debt figures are used only once filed. Note: Exxon's interest expense is net of the interest it capitalises (ASC 835-20); the two tags are the same figure (equal FY2017 to FY2020); added to interest expense it gives interest incurred, on the basis of Exxon's debt, which already holds its finance leases. Scoped to Exxon only: another company's `InterestPaidCapitalized` could sit beside a cash interest or a debt-only line, and each company is checked before it joins (companies as data, Decision 11).
- `math_engine.d8_interest` gains a step between the two existing ones (`_incurred`):
  1. Interest paid on debt (MSFT, #527): unchanged. Cash paid is before capitalising, so nothing is added to it.
  2. **Interest incurred on debt** (XOM, new): when the interest is not the cash fallback, the interest as resolved (today's chain: `interest_expense`) less `interest_not_on_debt` where filed (left out when below zero, as Exxon's FY2013 −123M, or not below the interest), plus `interest_capitalized` where filed (left out when negative). Method text: `<the resolved method> - interest not on debt: <trace> + interest capitalised (interest incurred = expensed + capitalised, ASC 835-20): <trace>`; facts are the interest's plus the two used, so the row's sources and the cost-of-debt chart's parts cite each filing, and the app can tell the basis from the part codes alone, without reading the text (product lead).
  3. Lease interest added (WMT, #497): unchanged. Its debt-only check reads the interest line's own facts, taken before step 2, so a capitalised fact never stops it.
  Never on the cash `interest_paid` fallback (`InterestPaidNet` is already net of capitalising).
- `interest_capitalized` and `interest_not_on_debt` join `OPTIONAL_ITEMS`, so a rebuild through an older map reads what it read.
- Map copy `concept_maps/<sha>.csv`, its `CHANGES.md` line, a `reading_rules.md` row: `READING_RULES_VERSION` 13 → 14 (a fresh Exxon run reads a different figure).
- Tests (`tests/analysis/test_lease_interest.py` or a new `tests/analysis/test_capitalised_interest.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`): the shipped map loads and lists the new scoped rows; `extract_facts` keeps both tags for XOM and skips them for the others; Exxon's FY2025 figures give (603 − 300 + 1,534) / 42,624 = 4.31%; each part alone; a non-debt figure below zero or not below the expense is left out; a year without the item keeps its interest; never on the `interest_paid` fallback; a negative capitalised figure is left out; Microsoft's #527 and Walmart's #497 cases unchanged; a database test reads both items through today's map and leaves them out through #527's map (`2b1a4489…`, archived in `concept_maps/`).
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot (`warren-20261122T153927Z`): `fundamentals ingest --all` (only Exxon gains facts); `fundamentals report --all`; `reproduce --all` to the cent, and `reproduce --all --rebuild` with as many runs rebuilding to identical rows after the ingest as before (each stored run reads through its own map). Then every stored run date built fresh in memory through main's map and the new one, with the same pinned market data and choices, none stored; list cost of debt, WACC, value per share and `below_risk_free` by year. Exit: only Exxon moves, only its `cost_of_debt` row and what follows from it (WACC, value per share), and no run note is added or removed except `below_risk_free` on the cost-of-debt chart, listed by year. Save a snapshot.

## Alternatives considered

- **Cash paid (`InterestPaid`), as #527 did for Microsoft.** Exxon tags it, but cash misses accrued and discount interest and includes the non-debt interest paid and needed a commercial-paper guard for Microsoft that Exxon, with paper in most years, would trip; the accrual sum needs no guard. Microsoft has no capitalised tag, so its rule stays cash.
- **A general rule for every company that tags capitalised interest.** J&J (`InterestCostsCapitalized`, 114M FY2025 against about 971M expense, #527 analyst review) and Apple (`InterestCostsIncurred` to FY2023) tag it too, but each company's tag, its non-debt interest and its debt basis must be checked first (the #497, #527 and this review's lessons). Filed as a follow-up, not done here.
- **Expense + capitalised only (the first draft).** Left Exxon's non-debt interest in and read 5.0% to 5.5% for FY2023 to FY2025 against a 3.4% to 3.8% debt table; dropped after the analyst's review.
- **A market cost of debt (a bond yield).** Practitioners prefer it, but it changes D8's method and needs a bond-price source Warren lacks (no free one); a decision for the owner, as #527 said.
- **A note only.** Leaves a number Warren knows is wrong when a filed figure fixes it.

## Files to change

`domains/fundamentals/concept_map.csv`, `domains/fundamentals/concept_maps/e43ad83d…csv` and `CHANGES.md`, `domains/analysis/math_engine.py`, `domains/analysis/reading_rules.md`, `domains/analysis/reading_rules.py` (version 14), `tests/analysis/test_capitalised_interest.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`. `docs/structure-guide.md` is unchanged: D8's method (interest over average book debt) is the same, only which filed lines make up a company's interest, as in #497 and #527, so no decision changes and no owner card is needed.

## Product impact

Exxon is in brief Q14 (line 263, OPEC cuts, an event question) and in any company screen of the Q3, Q4, Q7, Q8 and Q9 kind (lines 87, 93, 216, 223, 229: value per share, WACC and its parts, a rate shock, a margin what-if, the sensitivity grid) once the app lets a student pick Exxon. A fresh Exxon run's cost-of-debt row reads interest incurred on debt, 4.31% instead of 1.41% for FY2025: a slightly higher WACC and a slightly lower value per share (Step 2 gives the numbers, the years whose chart points change, the years where `below_risk_free` stops firing, and whether a debt what-if on the newest run still floors at the risk-free rate). The cost-of-debt chart's parts gain two part codes, `interest_capitalized` and `interest_not_on_debt` (product lead's Spanish for the label: "intereses capitalizados", with the why in the *Fuente* tab; for the other, "intereses que no son de deuda"; the front-end team adds both to its catalogue). The app can mark the basis from the part codes alone. Exxon's reported view (Q1, Q2 shapes) lists both as lines, since it shows every mapped item. Stored runs keep their rows: beside an older Exxon run of the same date stored under reading rules 6 to 13 the app shows the brief's "the reading rules changed" case (line 107); beside one with no recorded rules (most stored Exxon runs), the "either NULL" case (line 108) (product lead, blocker taken). No note, refusal code, param or field is added, renamed or removed. No other company changes.

## Design review (nov.22.2026)

- **Analyst, NO-GO on one blocker, taken.** Exxon's interest expense holds non-debt-related interest (FY2025 10-K 0000034088-26-000045, segment note: $0.3, $0.4 and $0.2 billion in 2025, 2024 and 2023), tagged `InterestExpenseOther` every year; adding the capitalised part on top overstated the rate by 0.2 to 1.0 points. Taken: new XOM item `interest_not_on_debt`, subtracted, read point-in-time (FY2023 and FY2024 were restated); FY2025 test (603 − 300 + 1,534) / 42,624 = 4.31%. Checks passed: capitalised interest is on construction of multiyear projects only, no equity-company interest found; lease interest sits inside the expense and the debt counts the leases; point-in-time by tag is fine. Taken into the text: the 10-K's debt table rates (3.43% long-term, 3.8% short-term) as the plausibility check, and a book rate below the Treasury yield is not by itself an error. Ideas: show the 10-K's average effective rate beside D8 (backlog); check J&J's non-debt interest before extending (in the follow-up).
- **Professor, GO, no blockers.** ASC 835-20 and Kieso et al. ch. 10 support expensed + capitalised = incurred; accrual over cash is sound; a market yield is the literature's preferred measure, rightly left to the owner. Taken: one principle stated for #497, #527 and this (interest incurred on the same debt the average counts; accrual where the parts are filed, cash paid on debt where they are not) in the reading-rules row and the lesson; IAS 23 cited beside ASC 835-20 (most students in Latin America learn IFRS); the lesson shows FY2025's 1.41% beside the debt table. Idea for the follow-up: Microsoft could move to the accrual rule if it ever tags a capitalised amount.
- **Explainer.** Fourteen gaps; taken: priority defined, the step order and the resolved interest named, the share capitalised by year corrected ("most" was not true every year), the stored-runs sentence clarified, the old-map test names its map, Step 2's exit made concrete, the structure guide said unchanged with the reason. The rest point to sources a reader of the linked files has (the rating line was dropped).
- **Product lead, one blocker, taken.** Most stored Exxon runs have no recorded reading rules, so beside a fresh run they get the "either NULL" case (brief line 108), not "the reading rules changed" (line 107); both named now. Taken: Q7 and Q9 kinds added; the Spanish label kept short; Step 2 lists the years the chart and `below_risk_free` change and the what-if floor; the basis can be read from part codes. Their own note: brief line 105 still says reading rules 11; the front-end team fixes it.
