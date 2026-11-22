# Backlog #527: Microsoft's cost of debt counts the interest it capitalises

Issue: https://github.com/sonderbot-ar/warren/issues/527 (from the #497 analyst review) · Branch `backlog-527-msft-capitalised-interest` · Version v0.10.31 when merged.

Status: In progress (nov.22.2026). Step 0.

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

(Millions of US$, the 10-Ks' annual figures, company facts nov.22.2026.) Microsoft's long-term debt is about 40 billion at coupons of roughly 2% to 4%, so 504M of interest on it (about 1.3%) is not what the debt costs. The newest stored run, `MSFT_2026-10-30_1`, reads a cost of debt of 3.11% (3,051M over average debt 98,106M), below that year's 4.98% average 10-year yield, so the cost-of-debt chart's `below_risk_free` note fires and a debt what-if floors at the risk-free rate.

**What Microsoft does file.** The debt note of every 10-K says: "Cash paid for interest on our debt for fiscal years 2026, 2025, and 2024 was $1.5 billion, $1.6 billion, and $1.7 billion, respectively", tagged `us-gaap:InterestPaid`. Cash paid is before any capitalising (capitalised interest is still paid to the lenders) and covers the debt only (finance-lease interest is paid as part of the lease payments, which Microsoft tags apart as `FinanceLeaseInterestPaymentOnLiability`). It is rounded to 100M from FY2016 on. Warren does not map `InterestPaid` today (it maps `InterestPaidNet`, cash paid net of capitalised interest, as the cash fallback for Caterpillar).

## Plan

**Step 0. This doc.**

**Step 1. Microsoft's cost of debt from interest paid on its debt plus finance-lease interest.**

- New optional map item `interest_paid_on_debt`: `us-gaap:InterestPaid`, priority 1, duration, USD, `companies=MSFT`; note: Microsoft's interest expense is net of the interest it capitalises (10-K Item 7, FY2025 and FY2026) and it tags no capitalised amount; this is its debt note's "cash paid for interest on our debt", before capitalising. Named `interest_…` so the cost-of-debt chart finds its filing (`single_values._interest_source` takes the first source whose item starts with "interest").
- The `finance_lease_interest` row (#497) becomes `companies=MSFT;WMT`.
- `math_engine.with_lease_interest` becomes `d8_interest` (still called by `cost_of_debt_year`), in this order:
  1. **Interest paid on debt** (MSFT): when the year reports `interest_paid_on_debt` and the average debt counted the finance-lease liability at both year ends (closing alone when the opening is not reported) and the year reports `finance_lease_interest`, interest is the two summed. When it counted the liability at **neither** end, interest is `interest_paid_on_debt` alone (the debt has no leases, so neither does the interest; Microsoft FY2016 and earlier). A year that straddles (one end with leases, Microsoft FY2017), or with lease debt but no lease interest, keeps today's interest, so no year mixes bases.
  2. **Lease interest added** (WMT, #497): unchanged, except that it now also requires the interest line to be debt-only by its tag (`us-gaap:InterestExpenseDebt`, `DEBT_ONLY_INTEREST_TAGS`). Walmart's is; Microsoft's `InterestExpenseNonoperating` is not, so a Microsoft year without `InterestPaid` can never count its lease interest twice. A GAAP tag's meaning, not a company, so it stays in code.
  3. Otherwise today's interest.
  The method text: `interest paid on debt: <trace> + finance lease interest: <trace> (in place of <today's trace>)`, and the facts are the two used, so the row's sources and the chart's parts cite them. Never on the cash `interest_paid` fallback.
- `interest_paid_on_debt` joins `OPTIONAL_ITEMS` (read only when the map in force has it), so a rebuild through an older map reads what it read.
- Map copy `concept_maps/<sha>.csv`, its `CHANGES.md` line, a `reading_rules.md` row: `READING_RULES_VERSION` 12 → 13 (a fresh Microsoft run reads a different figure).
- Tests (`tests/analysis/test_lease_interest.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`): the shipped map loads; the scoped rows are the CAT, PG, KO rows plus `finance_lease_interest` (MSFT, WMT) and `interest_paid_on_debt` (MSFT); `extract_facts` keeps `InterestPaid` for MSFT and skips it for the others; `cost_of_debt_year` on Microsoft's FY2026 figures gives (1,500 + 2,547) / 98,106 = 4.13%; no leases at either end gives cash alone; a straddle year, or lease debt without lease interest, keeps the accrual; a Microsoft-like year with lease interest but no `InterestPaid` keeps the accrual (no double count); Walmart's #497 cases unchanged; never on the `interest_paid` fallback.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot (`warren-20261122T053408Z`): `fundamentals ingest --all` (only MSFT gains facts); `fundamentals report --all`; `reproduce --all` to the cent and `reproduce --all --rebuild` with the same identical count as before. Then every stored run date built fresh in memory through main's map and the new one, with the same pinned market data and choices, none stored. List cost of debt, WACC, value per share and `below_risk_free` by year. Exit: only Microsoft moves; FY2017 years (the straddle) do not. Save a snapshot.

Expected from the filings (Microsoft, cost of debt today → new):

| FY | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Today | 2.70% | 2.80% | 3.13% | 3.23% | 3.37% | 3.42% | 3.27% | 3.05% | 3.05% | 4.10% | 2.84% | 3.11% |
| New | 2.14% | 2.48% | 3.13% (kept) | 3.04% | 3.32% | 3.61% | 3.33% | 3.44% | 3.41% | 3.40% | 3.59% | 4.13% |

The new series is steadier (3.0% to 3.6% from FY2018 to FY2025, then up with rates) and no longer drops when Microsoft capitalises more. It is cash, so it lags when debt grows quickly: in FY2015, FY2016 and FY2024 (Activision Blizzard's bonds, assumed in October 2023) the first coupons on new debt were not yet paid, and accrual interest also carries the write-up of bonds bought below par, so those years read lower than today. Rounding to 100M moves the rate by at most about 0.05 points.

## Alternatives considered

- **Add back capitalised interest to accrual interest.** The textbook fix (interest incurred = expensed + capitalised), but Microsoft files no capitalised amount, and Warren takes numbers only from tagged filings (an LLM reading the text would break "LLMs never produce financial numbers").
- **Cash interest only when it exceeds accrual interest on debt.** Would move FY2022–FY2023 and FY2025–FY2026 only, but picks the larger of two measures each year, which biases the rate up and has no rule a student could restate.
- **Only from FY2025, when the 10-K first says capitalising rose.** A date written in for one company; the capitalising began earlier in smaller amounts, and nothing in the filings marks a start.
- **A market cost of debt (a yield on Microsoft's bonds) where capitalising is large.** Practitioners prefer it, but it changes D8's method for one company and needs a bond-price source Warren does not have (no free one). That is a design change for the owner; filed as a note, not done.
- **A note only.** Keeps the number and says it reads low. Honest, but leaves a number Warren knows is wrong in every Microsoft WACC when a filed figure fixes it.

## Files to change

`domains/fundamentals/concept_map.csv`, `concept_maps/<new sha>.csv` and `CHANGES.md`, `domains/analysis/math_engine.py`, `domains/analysis/reading_rules.md`, `domains/analysis/reading_rules.py`, `tests/analysis/test_lease_interest.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` is unaffected (backlog item).

## Product impact

Serves brief Q3 (Microsoft's value per share and its assumptions) first: the cost-of-debt row of a fresh Microsoft run reads interest paid on debt plus finance-lease interest, 4.13% instead of 3.11% for FY2026, so a slightly higher WACC and a slightly lower value per share (Step 2 gives the numbers). Q4 and Q8 for Microsoft the same way. The cost-of-debt chart's points for FY2015–FY2016 and FY2018 on change, and their parts gain a new part code, `interest_paid_on_debt` (the app's catalogue should name it, e.g. "intereses pagados sobre la deuda (efectivo)"), beside `finance_lease_interest` (already named for Walmart). `below_risk_free` keeps firing on FY2026 (4.13% is still below the 4.98% yield) and on earlier years it can start or stop where the new rate crosses that year's yield (Step 2 lists them). Microsoft's reported view (Q1, Q2) may list `interest_paid_on_debt` and `finance_lease_interest` as lines, since it shows every mapped item. Stored runs keep their rows; beside an older Microsoft run of the same date the app shows the brief's "different map fingerprints" case (reading rules 12 and 13). No note, refusal code, param or field is added, renamed or removed. No other company changes: Walmart's #497 rule is the same (its interest tag is debt-only).
