# Backlog #533: ExxonMobil's cost of debt counts the interest it capitalises

Issue: https://github.com/sonderbot-ar/warren/issues/533 (from the #527 analyst review) · Branch `backlog-533-xom-capitalised-interest` · Version v0.10.33 when merged.

Status: In progress (design review).

## Problem

Warren's cost of debt (D8, `docs/build-plan.md` line 214) is a fiscal year's interest over the average of its two year-end debts (`math_engine.cost_of_debt_year`). For ExxonMobil the interest is the income statement's `us-gaap:InterestExpense`, which is net of the interest Exxon capitalises into projects under construction (ASC 835-20). Exxon capitalises most of its interest, so the line has collapsed while its debt has not. The newest stored run, `XOM_2026-10-30_2`, reads 1.41% (603M over average debt 42,624M), well below FY2025's average 10-year Treasury yield and the run's risk-free rate.

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

**Basis.** Exxon's debt in Warren counts finance leases: its long-term tag is `LongTermDebtAndCapitalLeaseObligations` (the run's debt note: "finance leases skipped: the debt tag already includes them"), and its interest expense is one line for all its borrowings, so lease interest and lease debt already match, as for Microsoft. Capitalised interest is interest on that same debt, moved into an asset's cost. So **interest expense + interest capitalised = interest incurred**, the textbook figure (ASC 835-20-30; Kieso, Weygandt and Warfield, *Intermediate Accounting*, ch. 10), on the same basis as the debt. Commercial paper is not a problem here (it was for #527's cash figure): the expense accrues the paper's discount, and the capitalised part is a share of interest incurred, paper included.

Interest incurred over average debt, read through today's map as known on 2026-10-30 (`load_history`, in memory):

| FY | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| Average debt (M) | 39,413 | 42,358 | 57,280 | 57,672 | 44,448 | 41,383 | 41,642 | 42,624 |
| Today (expense) | 1.94% | 1.96% | 2.02% | 1.64% | 1.80% | 2.05% | 2.39% | 1.41% |
| New (incurred) | 3.60% | 3.69% | 3.18% | 2.78% | 3.68% | 4.84% | 5.46% | 5.01% |
| Average 10-year yield | 2.91% | 2.14% | 0.89% | 1.45% | 2.95% | 3.96% | 4.21% | about 4.3% |

The new rates sit 0.7 to 2.3 points above the year's 10-year yield, which is where an AA-rated borrower with commercial paper and some acquired bonds (Pioneer, 2024, at fair value) would sit; today's sit below it from FY2022 on. (Stored runs built before #412 read a smaller FY2018 and FY2019 debt, without commercial paper; they keep their rows.)

## Plan

**Step 0. This doc.**

**Step 1. Exxon's cost of debt adds the interest it capitalises.**

- New optional map item `interest_capitalized`: `us-gaap:InterestPaidCapitalized` priority 1 and `us-gaap:InterestCostsCapitalized` priority 2, duration, USD, `companies=XOM`. Note: Exxon's interest expense is net of the interest it capitalises (ASC 835-20); the two tags are the same figure (equal FY2017 to FY2020); added to interest expense it gives interest incurred, on the basis of Exxon's debt, which already holds its finance leases. Scoped to Exxon only: another company's `InterestPaidCapitalized` could sit beside a cash interest or a debt-only line, and each company is checked before it joins (companies as data, Decision 11).
- `math_engine.d8_interest` gains a step between the two existing ones:
  1. Interest paid on debt (MSFT, #527): unchanged. Cash paid is before capitalising, so nothing is added to it.
  2. **Interest capitalised added** (XOM, new): when the year reports `interest_capitalized` and the interest is not the cash fallback, interest is the resolved interest plus it. Method text: `<today's method> + interest capitalised (ASC 835-20, interest incurred = expensed + capitalised): <trace>`; facts are the interest's facts plus the capitalised fact, so the row's sources and the cost-of-debt chart's parts cite both filings. A capitalised figure of zero adds zero; a negative one is left out and the interest kept (a negative capitalised interest has no meaning; none is filed).
  3. Lease interest added (WMT, #497): unchanged, applied after step 2 (it needs a debt-only tag; Exxon's is not, so the two never meet today).
  Never on the cash `interest_paid` fallback (`InterestPaidNet` is already net of capitalising; adding the capitalised part would make it cash paid, a different basis).
- `interest_capitalized` joins `OPTIONAL_ITEMS`, so a rebuild through an older map reads what it read.
- Map copy `concept_maps/<sha>.csv`, its `CHANGES.md` line, a `reading_rules.md` row: `READING_RULES_VERSION` 13 → 14 (a fresh Exxon run reads a different figure).
- Tests (`tests/analysis/test_lease_interest.py` or a new `tests/analysis/test_capitalised_interest.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`): the shipped map loads and lists the new scoped rows; `extract_facts` keeps both tags for XOM and skips them for the others; Exxon's FY2025 figures give (603 + 1,534) / 42,624 = 5.01%; a year without the item keeps its interest; never on the `interest_paid` fallback; a negative capitalised figure is left out; Microsoft's #527 and Walmart's #497 cases unchanged; a database test reads the item through today's map and leaves it out through the map before this change.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot (`warren-20261122T153927Z`): `fundamentals ingest --all` (only Exxon gains facts); `fundamentals report --all`; `reproduce --all` to the cent and `reproduce --all --rebuild` with the same identical count before and after. Then every stored run date built fresh in memory through main's map and the new one, with the same pinned market data and choices, none stored; list cost of debt, WACC, value per share and `below_risk_free` by year. Exit: only Exxon moves, and only its `cost_of_debt` row (and what follows from it). Save a snapshot.

## Alternatives considered

- **Cash paid (`InterestPaid`), as #527 did for Microsoft.** Exxon tags it, but cash misses accrued and discount interest (the FY2025 gap: incurred 2,137M against cash 1,752M) and needed a commercial-paper guard for Microsoft that Exxon, with paper in most years, would trip; the accrual sum needs no guard. Microsoft has no capitalised tag, so its rule stays cash.
- **A general rule for every company that tags capitalised interest.** J&J (`InterestCostsCapitalized`, 114M FY2025 against about 971M expense) and Apple (`InterestCostsIncurred` to FY2023) tag it too, but each company's tag and debt basis must be checked first (the #497 and #527 lessons). Filed as a follow-up, not done here.
- **A market cost of debt (a bond yield).** Practitioners prefer it, but it changes D8's method and needs a bond-price source Warren lacks (no free one); a decision for the owner, as #527 said.
- **A note only.** Leaves a number Warren knows is wrong when a filed figure fixes it.

## Files to change

`domains/fundamentals/concept_map.csv`, `domains/fundamentals/concept_maps/<new sha>.csv` and `CHANGES.md`, `domains/analysis/math_engine.py`, `domains/analysis/reading_rules.md`, `domains/analysis/reading_rules.py` (version), tests as above, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Exxon is in brief Q14 (OPEC cuts, an event question) and in any company screen of the Q3, Q4 and Q8 kind (value per share, WACC and its parts, a what-if) once the app lets a student pick Exxon. A fresh Exxon run's cost-of-debt row reads interest incurred, 5.01% instead of 1.41% for FY2025: a slightly higher WACC and a slightly lower value per share (Step 2 gives the numbers). The cost-of-debt chart's points for every year with a capitalised figure change, and their parts gain a new part code, `interest_capitalized` (suggested Spanish: "intereses capitalizados (sumados a los intereses del estado de resultados)"; not in the catalogue yet, the front-end team adds it). `below_risk_free` should stop firing on Exxon's recent years (Step 2 checks). Exxon's reported view (Q1, Q2 shapes) may list `interest_capitalized` as a line, since it shows every mapped item. Stored runs keep their rows; beside an older Exxon run of the same date the app shows the brief's "the reading rules changed" case (rules 13 and 14). No note, refusal code, param or field is added, renamed or removed. No other company changes.

## Design review

(pending)
