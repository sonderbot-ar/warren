# Backlog #497: Walmart's cost of debt counts its finance-lease interest

Issue: https://github.com/sonderbot-ar/warren/issues/497 (from the #481 analyst review) · Branch `backlog-497-wmt-lease-interest` · Version v0.10.29 when merged.

Status: In progress (nov.22.2026).

## Problem

Warren's cost of debt (D8) is a fiscal year's interest over the average of its two year-end debts (`math_engine.cost_of_debt_year`). For Walmart the two are on different bases:

- **Debt includes finance leases.** `math_engine.debt_parts` adds `finance_lease_liabilities` (`FinanceLeaseLiability`) to debt. Walmart files it at every year end from 2020-01-31 (ASC 842, adopted in FY2020): 4,818M then, 6,761M at 2026-01-31.
- **Interest leaves finance-lease interest out.** Walmart's income statement splits "Interest" into "Debt", "Finance lease" and "Interest income". The map reads WMT's interest from `InterestExpenseDebt` (`interest_expense` priority 3; the note already says "interest on debt only (finance-lease interest excluded)"), because Walmart tags neither `InterestExpenseNonoperating` nor `InterestExpense`. The finance-lease line is `FinanceLeaseInterestExpense`: 306M for FY2020 (first filed in the FY2020 10-K, 2020-03-20, accession 0000104169-20-000011) up to 383M for FY2026.

So from FY2020 on, Walmart's cost of debt divides debt-only interest by debt plus leases, and reads low. On the newest WMT run (2026-10-30, FY2026): interest 2,318M over average debt 48,657M is 4.76%, just below the 4.98% average 10-year yield, so the `below_risk_free` note fires and a debt what-if floors. With the finance-lease line, 2,701M / 48,657M is 5.55%.

Before FY2020 the two bases already agree: Walmart's capital lease obligations (`CapitalLeaseObligations`, 7,412M at 2019-01-31) are not mapped, so they are not in debt, and their interest (`InterestExpenseLesseeAssetsUnderCapitalLease`) is not in interest either. `FinanceLeaseInterestExpense` and `FinanceLeaseLiability` both start with FY2020 in Walmart's annual filings, so adding the first wherever it is reported keeps the two in step. One year straddles: FY2020's average debt opens at 2019-01-31, before leases were on the balance sheet, so FY2020's denominator is half on the old basis while its interest would be fully on the new one (FY2020: 2,568M / 52,545M = 4.89% with the lease interest, 4.30% without). That year is used only by runs dated between the FY2020 10-K (2020-03-20) and the FY2021 10-K (2021-03-19); it is noted in Results, not corrected.

### Who else files the tag (company facts, nov.22.2026)

| Company | Interest tag Warren reads | Files `FinanceLeaseInterestExpense` | Effect of adding it everywhere |
|---|---|---|---|
| WMT | `InterestExpenseDebt` (debt only) | FY2020–FY2026 | **Fixes the mismatch** |
| MSFT | `InterestExpenseNonoperating` / `InterestExpense` | FY2016–FY2026 (2,547M FY2026) | **Double count**: Microsoft's "Interest expense" line already includes finance-lease interest (its 10-K's other income note) |
| AAPL, KO, PG, JNJ, CAT, XOM | totals | no | none |

So the line must be added for Walmart only.

## Plan

**Step 0. This doc.**

**Step 1. Walmart's finance-lease interest in its cost of debt.**
- New optional item `finance_lease_interest` in `concept_map.csv`: `us-gaap:FinanceLeaseInterestExpense`, priority 1, duration, USD, `companies=WMT`, note: Walmart's interest line is debt only while its debt includes finance leases; Microsoft files the tag too but its interest total already includes it.
- `concepts.load_concept_map`: a row limited to some companies may be priority 1 when **every** row of its item is limited (an item only some companies read). The rule it relaxes exists so that every other company keeps an item's first tag (#341); an item with no unlimited row has no first tag for anyone else to keep. A priority-1 scoped row on an item that also has an unlimited row is still refused.
- `math_engine.cost_of_debt_year`: when interest comes from `interest_expense` (not the cash `interest_paid` fallback) and the year reports `finance_lease_interest`, the two are added: the resolved interest's value, its method text (`… + finance lease interest: <trace>`) and its facts (so the row's sources and the input chart's parts cite both filings). `finance_lease_interest` joins the items the history loads (`ITEMS`), read only when the map in force has it (like `debt_current_total`, #408), so a rebuild through an older map reads what that map read. Not added to the `interest` chain: putting a two-item alternative first would mark every other company's plain interest a "fallback" and change every stored run's rebuilt text.
- The map's copy in `concept_maps/` and its `CHANGES.md` line; a `reading_rules.md` row (rules version unchanged: which figures a run reads is pinned by the map's fingerprint, as for #341).
- Tests: the shipped map loads with the new row; a scoped priority-1 row is accepted when all its item's rows are scoped and refused beside an unscoped row; the list of scoped rows is the CAT, PG, KO rows plus this one; `extract_facts` keeps the tag for WMT and skips it for MSFT; `cost_of_debt_year` adds a reported finance-lease interest, leaves a year without it unchanged, never adds it to cash interest; a rebuild through a map without the item reads no lease interest.
- Exit: full suite, `ruff check`, `ruff format --check` green.

**Step 2. Real data.** On the restored snapshot (`warren-20261121T001838Z`): `fundamentals ingest --all` (only WMT gains facts; MSFT's are skipped as `company_scope`); `fundamentals report --all` passes; `reproduce --all` reproduces every stored run to the cent; `reproduce --all --rebuild` gives the same identical count as before the ingest (stored runs read through their own map, which has no such item). Then build every stored WMT date fresh in memory through the old map and the new one (same pinned market data and choices, none stored) and list cost of debt, WACC, value per share and whether `below_risk_free` fires, by year. Exit: no non-WMT run moves; WMT runs whose cost-of-debt year is FY2020 or later move, earlier ones do not. Save a snapshot after the ingest.

## Alternatives considered

- **Leave finance leases out of Walmart's cost-of-debt denominator.** Fixes the ratio but makes D8 compute debt two ways (with leases for net debt and the WACC weight, without for the rate), and the rate would then not describe the debt it weighs. Adding the missing interest keeps one debt.
- **Add `FinanceLeaseInterestExpense` to the `interest` chain as a first alternative (`interest_expense + finance_lease_interest`).** Same numbers, but every other company's interest would become alternative 2, a "fallback", changing the method text of every stored run on rebuild.
- **Rank the tag inside `interest_expense`.** The map picks one tag per item, never a sum.
- **A Walmart rule in the engine.** Puts a company in code; the guardrail is companies as data (Decision 11).
- **Read the pre-FY2020 capital lease interest and obligations too.** Would also be consistent, but changes every older Walmart run and their debt, for a mismatch that does not exist there today. Not now.

## Files to change

`domains/fundamentals/concept_map.csv`, `concept_maps/<new sha>.csv` and `CHANGES.md`, `domains/fundamentals/concepts.py`, `domains/analysis/math_engine.py`, `domains/analysis/reading_rules.md`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, `tests/analysis/` (cost of debt), this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` that use the cost of debt (Q3, Q5, Q8, value per share and the debt what-if): fresh Walmart runs whose cost-of-debt year is FY2020 or later get a higher, consistent cost of debt, so a higher WACC and a lower value per share (Step 2 gives the numbers). Stored runs keep their rows. The `below_risk_free` note stops firing on the newest Walmart run, and a Walmart debt what-if stops flooring at the risk-free rate there. The `cost_of_debt` row's sources and the cost-of-debt chart's parts for those years gain a second filing fact, `finance_lease_interest` (a new part code the app's catalogue should name: "intereses de arrendamientos financieros"). No note, refusal code, param or field is added, renamed or removed. Beside an older WMT run of the same date the app shows the brief's "different map fingerprints" case.
