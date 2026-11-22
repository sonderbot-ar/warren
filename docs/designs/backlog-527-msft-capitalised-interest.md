# Backlog #527: Microsoft's cost of debt counts the interest it capitalises

Issue: https://github.com/sonderbot-ar/warren/issues/527 (from the #497 analyst review) · Branch `backlog-527-msft-capitalised-interest` · Version v0.10.31 when merged.

Status: Done (v0.10.31, nov.22.2026; PR #532, merge `af81413`, after CI green and a gatekeeper GO).

## Problem

Warren's cost of debt (D8, `docs/build-plan.md` line 214) is a fiscal year's interest over the average of its two year-end debts (`math_engine.cost_of_debt_year`). For Microsoft the interest is the income statement's `InterestExpenseNonoperating` (`InterestExpense` before FY2023), and its debt counts finance leases (`FinanceLeaseLiability`). Two things sit in that interest line:

- **Finance-lease interest is inside it.** Microsoft files `FinanceLeaseInterestExpense` (2,547M FY2026, 1,417M FY2025), and the FY2025 10-K, Item 7, says interest expense moved "offset in part by higher finance lease interest expense" (accession 0000950170-25-100235). So, unlike Walmart (#497), lease interest and lease debt already match.
- **Capitalised interest is taken out of it.** The FY2026 10-K, Item 7 (accession 0001193125-26-323660): "Interest expense increased primarily due to higher finance lease interest expense, offset in part by higher capitalization of debt interest expense." Interest on money borrowed while data centres are being built goes into the buildings' cost, not the income statement. Microsoft does not tag the amount: neither `InterestCostsCapitalized` nor `InterestCostsIncurred` is in its company facts or in the FY2026 10-K's XBRL (checked nov.22.2026).

So the debt part of the line has collapsed while the debt has not. Interest expense less finance-lease interest:

| FY | Interest expense | Finance-lease interest | On debt (accrual, after capitalising) | Cash paid for interest on debt (`InterestPaid`) |
|---|---|---|---|---|
| 2022 | 2,063 | 429 | 1,634 | 1,900 |
| 2023 | 1,968 | 501 | 1,467 | 1,700 |
| 2024 | 2,935 | 734 | 2,201 | 1,700 |
| 2025 | 2,385 | 1,417 | 968 | 1,600 |
| 2026 | 3,051 | 2,547 | 504 | 1,500 |

(Millions of US$, the 10-Ks' annual figures, company facts nov.22.2026.) Microsoft's long-term debt is about 40 billion at coupons of roughly 2% to 4%, so 504M of interest on it (about 1.3%) is not what the debt costs. The newest stored run, `MSFT_2026-10-30_1`, reads a cost of debt of 3.11% (3,051M over average debt 98,106M), below FY2026's 4.25% average 10-year yield and the run's 4.98% risk-free rate, so the cost-of-debt chart's `below_risk_free` note fires and a debt what-if floors at the risk-free rate.

**What Microsoft does file.** The debt note of every 10-K says: "Cash paid for interest on our debt for fiscal years 2026, 2025, and 2024 was $1.5 billion, $1.6 billion, and $1.7 billion, respectively", tagged `us-gaap:InterestPaid`. Cash paid is before any capitalising (capitalised interest is still paid to the lenders) and covers the debt only (finance-lease interest is paid as part of the lease payments, which Microsoft tags apart as `FinanceLeaseInterestPaymentOnLiability`). It is rounded to 100M from FY2016 on. Warren does not map `InterestPaid` today (it maps `InterestPaidNet`, cash paid net of capitalised interest, as the cash fallback for Caterpillar).

## Plan

**Step 0. This doc.**

**Step 1. Microsoft's cost of debt from interest paid on its debt plus finance-lease interest.**

- New optional map item `interest_paid_on_debt`: `us-gaap:InterestPaid`, priority 1, duration, USD, `companies=MSFT`; note: Microsoft's interest expense is net of the interest it capitalises (10-K Item 7, FY2025 and FY2026) and it tags no capitalised amount; this is its debt note's "cash paid for interest on our debt", before capitalising. Named `interest_…` so the cost-of-debt chart finds its filing (`single_values._interest_source` takes the first source whose item starts with "interest").
- The `finance_lease_interest` row (#497) becomes `companies=MSFT;WMT`.
- `math_engine.with_lease_interest` becomes `d8_interest` (still called by `cost_of_debt_year`), in this order:
  1. **Interest paid on debt** (MSFT): when the year reports `interest_paid_on_debt` and `finance_lease_interest`, the average debt counted the finance-lease liability at both year ends (closing alone when the opening is not reported), and it counted no short-term borrowings or commercial paper above zero at either, interest is the two summed. Every other year keeps today's interest: a year with leases at one end only (Microsoft FY2017) or at neither (FY2016 and earlier, where the 10-Ks name no capitalising; analyst), or with commercial paper in the average (FY2024 and FY2025: 6,693M at 2024-06-30, whose interest is paid as a discount at maturity and is not in the cash paid for interest on debt; analyst), so no year mixes bases.
  2. **Lease interest added** (WMT, #497): unchanged, except that it now also requires the interest line to be debt-only by its tag (`us-gaap:InterestExpenseDebt`, `DEBT_ONLY_INTEREST_TAGS`). Walmart's is; Microsoft's `InterestExpenseNonoperating` is not, so a Microsoft year without `InterestPaid` can never count its lease interest twice. A GAAP tag's meaning, not a company, so it stays in code.
  3. Otherwise today's interest.
  The method text: `interest paid on debt (cash, before capitalised interest): <trace> + finance lease interest: <trace> (in place of <today's trace>)` (professor), and the facts are the two used, so the row's sources and the chart's parts cite them. Never on the cash `interest_paid` fallback.
- `interest_paid_on_debt` joins `OPTIONAL_ITEMS` (read only when the map in force has it), so a rebuild through an older map reads what it read.
- Map copy `concept_maps/<sha>.csv`, its `CHANGES.md` line, a `reading_rules.md` row: `READING_RULES_VERSION` 12 → 13 (a fresh Microsoft run reads a different figure).
- Tests (`tests/analysis/test_lease_interest.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`): the shipped map loads; the scoped rows are the CAT, PG, KO rows plus `finance_lease_interest` (MSFT, WMT) and `interest_paid_on_debt` (MSFT); `extract_facts` keeps `InterestPaid` for MSFT and skips it for the others; `cost_of_debt_year` on Microsoft's FY2026 figures gives (1,500 + 2,547) / 98,106 = 4.13%; no leases at either end, a straddle year, lease debt without lease interest, or commercial paper above zero at either year end keeps the accrual (paper of zero does not count); a Microsoft-like year with lease interest but no `InterestPaid` keeps the accrual (no double count); Walmart's #497 cases unchanged; never on the `interest_paid` fallback.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot (`warren-20261122T053408Z`): `fundamentals ingest --all` (only MSFT gains facts); `fundamentals report --all`; `reproduce --all` to the cent and `reproduce --all --rebuild` with the same identical count as before. Then every stored run date built fresh in memory through main's map and the new one, with the same pinned market data and choices, none stored. List cost of debt, WACC, value per share and `below_risk_free` by year. Exit: only Microsoft moves, and only runs whose cost-of-debt year is FY2018 to FY2023 or FY2026 (on real data FY2018 and FY2020 do not move either; Results); Walmart does not move (professor). Save a snapshot.

Expected from the filings (Microsoft, cost of debt today → new; every stored Microsoft run is dated 2019-04-01 or later, so reads FY2018 on):

| FY | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| Today | 3.23% | 3.37% | 3.42% | 3.27% | 3.05% | 3.05% | 4.10% | 2.84% | 3.11% |
| New | 3.04% | 3.32% | 3.61% | 3.33% | 3.44% | 3.41% | 4.10% (kept: paper) | 2.84% (kept: paper) | 4.13% |

FY2025, a year the 10-K says capitalising rose, stays low because the commercial paper repaid during it is in its opening debt: the cash figure would miss that paper's interest, so the rule keeps the expense rather than mix bases. It is said straight in the lesson. Cash paid also misses the yearly unwinding of the discount and exchange premium on Microsoft's bonds (about 188M a year in the FY2026 debt table; Activision's notes carry 1.35% to 4.50% coupons against 5.16% to 5.49% effective rates), so the new rate reads about 0.2 points low (analyst). Rounding to 100M moves it by at most 50M / 98,106M, about 0.05 points. The lease interest stays the accrual figure: Microsoft's finance-lease interest paid (`FinanceLeaseInterestPaymentOnLiability`) equals it in every year but FY2025 (1,372M against 1,417M), so the two bases differ by at most 0.05 points (professor).

## Results (Step 2, nov.22.2026)

On the restored snapshot `warren-20261122T053408Z`.

- **Before anything changed.** `reproduce --all --rebuild`: 909 of 909 stored runs reproduced to the cent, 698 of 909 rebuilt to identical rows.
- **Ingest.** `fundamentals ingest --all`: Microsoft gains 165 facts (`InterestPaid` and `FinanceLeaseInterestExpense`, years and quarters, every filing's version); every other company gains none (Walmart already had its lease interest). `fundamentals report --all`: 0 unexplained gaps for all eight companies.
- **Stored runs after the ingest.** 909 of 909 reproduced to the cent; 698 of 909 rebuilt to identical rows, the same count as before (each run reads through its own map, which has no such item).
- **Fresh runs.** Every stored run date (899 company-dates) built twice in memory, pinned market data and choices, through main's map (`fa48b47307cf`; with it the code reads as main does) and today's; none stored, none refused. Only Microsoft moves, 67 of 115 dates, and on each only the `cost_of_debt` row (no run note added or removed). **Walmart does not move** (professor).

| Runs dated | Moved | Cost of debt (last moved run of the year) | WACC | Value per share |
|---|---|---|---|---|
| 2019 | 6 of 11 | 3.37% → 3.32% (FY2019) | 5.59% → 5.59% | +0.05% |
| 2020 | 8 of 14 | 3.37% → 3.32% (FY2019) | 4.39% → 4.39% | +0.04% to +0.06% |
| 2021 | 6 of 14 | 3.27% → 3.33% (FY2021) | 5.26% → 5.27% | −0.02% to −0.03% |
| 2022 | 15 of 15 | 3.05% → 3.44% (FY2022) | 9.28% → 9.29% | −0.02% to −0.13% |
| 2023 | 17 of 17 | 3.05% → 3.41% (FY2023) | 9.67% → 9.68% | −0.08% to −0.13% |
| 2024 | 8 of 14 | 3.05% → 3.41% (FY2023) | 10.20% → 10.21% | −0.08% to −0.11% |
| 2025 | 0 of 14 | (FY2024, FY2025: commercial paper, kept) | | |
| 2026 | 7 of 16 | 3.11% → 4.13% (FY2026) | 11.45% → 11.47% | −0.22% to −0.27% |

  Which runs do not move, and why: those reading FY2018 (9,072M of short-term borrowings at 2017-06-30), FY2024 and FY2025 (commercial paper at 2024-06-30), and FY2020 (Microsoft's FY2020 10-K did not tag its cash interest; the figure first appears in the FY2021 10-K, 2021-07-29, so a run of that time cannot read it, point-in-time). The newest run, as of 2026-10-30: cost of debt 3.11% → 4.13%, WACC 11.45% → 11.47%, value per share $203.55 → $203.08. The cost of debt moves up to a point, the WACC about 2 basis points: Microsoft's debt is about 3% of its capital at market value. Revenue and EBIT forecasts do not read the cost of debt, so no forecast-error score moves. `below_risk_free` against each fiscal year's average 10-year yield fires on the same years as before (FY2019 2.74%, FY2021 1.11% and FY2022 1.93% sit below both rates; FY2023 3.54% and FY2026 4.25% above both).
- Snapshot saved after the ingest.

## Alternatives considered

- **Add back capitalised interest to accrual interest.** The textbook fix (interest incurred = expensed + capitalised), but Microsoft files no capitalised amount, and Warren takes numbers only from tagged filings (an LLM reading the text would break "LLMs never produce financial numbers").
- **Cash interest in years with no leases too (the first draft).** Moved FY2015 and FY2016 down (2.70% → 2.14%, 2.80% → 2.48%) where the 10-Ks name no capitalising and the cash figure lags fast-growing debt; dropped after the analyst's review.
- **Cash interest only when it exceeds accrual interest on debt.** Would move FY2022–FY2023 and FY2025–FY2026 only, but picks the larger of two measures each year, which biases the rate up and has no rule a student could restate.
- **Only from FY2025, when the 10-K first says capitalising rose.** A date written in for one company; the capitalising began earlier in smaller amounts, and nothing in the filings marks a start.
- **A market cost of debt (a yield on Microsoft's bonds) where capitalising is large.** Practitioners prefer it, but it changes D8's method for one company and needs a bond-price source Warren does not have (no free one). That is a design change for the owner; filed as a note, not done.
- **A note only.** Keeps the number and says it reads low. Honest, but leaves a number Warren knows is wrong in every Microsoft WACC when a filed figure fixes it.

## Files to change

`domains/fundamentals/concept_map.csv`, `concept_maps/<new sha>.csv` and `CHANGES.md`, `domains/analysis/math_engine.py`, `domains/analysis/reading_rules.md`, `domains/analysis/reading_rules.py`, `tests/analysis/test_lease_interest.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` is unaffected (backlog item).

## Product impact

Serves brief Q3 (line 87, Microsoft's value per share and its assumptions), the only brief question about Microsoft this touches: the cost-of-debt row of a fresh Microsoft run reads interest paid on debt plus finance-lease interest, 4.13% instead of 3.11% for FY2026, so a slightly higher WACC and a slightly lower value per share (Step 2 gives the numbers). Microsoft's WACC and value per share move on the same screens the Walmart questions use (Q4, Q8). The cost-of-debt chart's points for FY2018 to FY2023 and FY2026 change, and their parts gain a new part code, `interest_paid_on_debt` (product lead's Spanish: "intereses pagados en efectivo sobre la deuda (incluye los que la empresa capitaliza)"), beside `finance_lease_interest` ("intereses de arrendamientos financieros"; neither is in the brief's catalogue yet, the front-end team adds both). A point read in cash carries `interest_paid_on_debt` among its parts, so the app can mark its basis without a new param. `below_risk_free` fires on the same years as before (Step 2): FY2026's 4.13% is still below that year's 4.25% average yield, and FY2023's 3.41% below its 3.54%; a debt what-if on the newest run still floors at the risk-free rate. Microsoft's reported view (Q1, Q2) may list `interest_paid_on_debt` and `finance_lease_interest` as lines, since it shows every mapped item. Stored runs keep their rows; beside an older Microsoft run of the same date the app shows the brief's "the reading rules changed" case (rules 12 and 13, brief line 107), or the "either NULL" case beside a run with no recorded rules (line 108), not the "different map fingerprints" case (product lead). No note, refusal code, param or field is added, renamed or removed. No other company changes: Walmart's #497 rule is the same (its only interest tag is debt-only).

## Design review (nov.22.2026)

- **Analyst, NO-GO on one blocker, taken.** Microsoft's `InterestPaid` is "cash paid for interest on our debt" in every 10-K checked (FY2014 0001193125-14-289961, FY2015 0001193125-15-272806, FY2017 0001564590-17-014900, FY2018 0001564590-18-019062, FY2026); no capitalised amount is tagged; FY2017 straddles; the guard cannot move Walmart (its only interest tag is `InterestExpenseDebt`, FY2008 to FY2026); FY2026 arithmetic checks. Blocker: FY2024 and FY2025 put cash interest that leaves out commercial-paper interest over a debt that counts the paper (FY2024 10-K 0000950170-24-087843: "Interest expense increased due to the issuance of commercial paper"); the doc's Activision explanation was wrong. Taken: no cash path with short-term borrowings or paper at either year end, with tests; the explanation and table corrected. Idea taken: keep accrual where no leases are counted (no capitalising named there). Notes taken into Step 2's text: cash misses the discount unwinding (about 0.2 points low). Ideas filed as backlog: Exxon's interest expense is net of capitalised interest too (FY2025: expense 603M, `InterestPaid` 1,752M including capitalised, `InterestPaidNet` 218M; `XOM_2026-10-30_1` reads 1.47%); J&J tags `InterestCostsCapitalized` (114M FY2025); Apple tags `InterestCostsIncurred` through FY2023.
- **Professor, GO, no blockers.** ASC 835-20: capitalised interest is interest incurred, moved into the asset's cost, so expensed interest over all debt understates the book rate; cash paid is the best tagged stand-in; Koller, Goedhart and Wessels and Damodaran prefer a market yield, rightly left to the owner. Taken: the method text says "cash, before capitalised interest"; why the lease interest stays accrual (Step 2's text); Step 2 shows Walmart does not move. XBRL US rule DQC.US.0065 treats `InterestPaid` as including capitalised interest and `InterestPaidNet` as excluding it (seen through search only); cited here and in the CHANGES.md line.
- **Explainer.** Fifteen gaps; taken: the product impact's years now match the table, the neither-end and paper cases are spelled out, the yield and rounding sums are shown. The rest are pointers a reader of the code has (`OPTIONAL_ITEMS`, the map's priority).
- **Product lead, no blocker.** Taken: Q4 and Q8 are Walmart's, so Q3 is the one Microsoft question; the two-runs case is "the reading rules changed", not "different map fingerprints" (the v0.10.29 team-sync entry made the same slip; the front-end team corrects the brief); both part codes need catalogue names, which the front-end team adds.
- **Gatekeeper (PR #532), GO, no blockers.** 2,773 passed; reading-rules fingerprint and map copy match; `MSFT_2026-10-30_1` and `WMT_2026-10-30_1` rebuild identically through their own maps; Walmart's FY2026 still 5.55%; no test weakened (the fixture retag keeps its assertions; the ingest test is broader). Notes filed as #534 (the reading-rules row's "FY2018 on" wording, a short-term borrowings test, an empty-facts guard).
