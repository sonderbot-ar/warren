# Backlog #421: the current portion read on the same basis as the non-current debt

Issue: https://github.com/sonderbot-ar/warren/issues/421 (from the #415 design and gatekeeper reviews), items 1 to 3 · Branch `backlog-421-current-lease-debt`. Item 4 is an app idea for the front-end team and stays open.

## Problem

1. **Exxon's current finance-lease debt is never counted.** Exxon tags its non-current debt only as `LongTermDebtAndCapitalLeaseObligations` (lease-inclusive, map `debt_noncurrent` priority 2), so D3 skips the finance-lease line (`math_engine._lease_inclusive`, "finance leases skipped: the debt tag already includes them"). Its current portion is tagged twice in the 10-K: `LongTermDebtCurrent` (debt only, `debt_current` priority 1) and `LongTermDebtAndCapitalLeaseObligationsCurrent` (debt and the current finance-lease portion, priority 2). Priority 1 wins, so the current lease portion falls between the two: counted neither in the current portion nor through the lease line. Exxon's year ends in Warren's data (latest filing, millions):

   | Year end | `LongTermDebtCurrent` | `…AndCapitalLeaseObligationsCurrent` | Gap |
   |---|---|---|---|
   | 2018-12-31 | 4,070 | 4,070 | 0 |
   | 2019-12-31 | 1,617 | 1,701 | 84 |
   | 2020-12-31 to 2024-12-31 | equal | equal | 0 |
   | 2025-12-31 | 6,200 | 6,234 | 34 |
   | 2010-12-31 | 345 | 12,227 | (the long-term debt again, under the wrong tag, in a 10-Q of 2011-05-05) |

   The gap is the current finance-lease portion (the issue's reading; the 2019 and 2025 10-K debt notes show it as "finance lease obligations" due within one year). The only other company that tags both current tags at one date is Coca-Cola at 2023-12-31, where they are equal and its non-current tag is the plain one. So the effect is small: Exxon's runs whose balance date, history year or cost-of-debt year end is 2019-12-31 or 2025-12-31, by $84M or $34M. It matters because the rule should hold by construction: when the non-current debt includes leases, the current debt must too, or the leases due within a year disappear.

2. **A point-in-time test is missing for #415's rule.** P&G's FY2009 parts (balance date 2009-06-30) were first filed 2010-08-13; its total was filed 2009-10-29. A history read between those dates must count the total, and after 2010-08-13 the parts.

3. **The debt rules' measurements don't list near-misses**: balance dates with a filed total where #408, #412 or #415 did not fire, and how close each came (Exxon 2011-03-31 was found by hand).

## Plan

- **Step 0.** This design doc.

- **Step 1. The current portion on the non-current debt's basis.**
  - Concept map: `us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent` moves from `debt_current` priority 2 to a new optional item `debt_current_with_leases` (priority 1); `debt_current` keeps `LongTermDebtCurrent` (1) and CAT's maturities tag (now 2). New map copy in `concept_maps/` and its line in `CHANGES.md`. No re-ingest: facts are stored by tag and a tag may change item (`sync_concepts`).
  - `domains/fundamentals/facts.get_facts`: when `debt_current` is asked and the map in force has `debt_current_with_leases`, both items and `debt_noncurrent` are read and merged into `debt_current` per balance date (`_current_on_noncurrent_basis`), so every reader (the engine's history, the annual check, the reported view) sees one current portion:
    - only one of the two tags at a date: that one (as before: the lease-inclusive tag was the fallback);
    - both: the lease-inclusive one when the same date's `debt_noncurrent` is lease-inclusive and the lease-inclusive figure is at least the plain one and at most `TOO_BIG` (1.5) times it; otherwise the plain one. The bound keeps Exxon's 2010-12-31 mis-tag (12,227M beside 345M) out.
    - `debt_current_with_leases` and `debt_noncurrent` are returned only if asked.
  - A map without the new item (every stored run's) reads exactly what it read before: the merge is skipped and the tag is still `debt_current` priority 2 there.
  - `READING_RULES_VERSION` 8 → 9 with its row in `reading_rules.md`.
  - No new run note: the debt row's method already names the tag (`LongTermDebtAndCapitalLeaseObligationsCurrent`) and the run already carries "finance leases skipped: the debt tag already includes them".
  - Tests (`tests/fundamentals/test_current_on_noncurrent_basis.py`, `tests/analysis/test_current_lease_debt.py`): both tags with a lease-inclusive non-current → the larger counts in debt, working capital and the cost of debt; a plain non-current → the plain current; only the lease-inclusive tag → it (the old fallback); a lease-inclusive figure above 1.5× or below the plain one → the plain one; the merged fact is named `debt_current` and keeps its own tag and filing; through #415's map (`c621cb3eaf6e`) the run reads what it read before.
  - Exit: full suite and ruff clean.

- **Step 2. Tests the #415 reviews asked for.** P&G FY2009 point in time (total filed before the parts: total counted on a date between the filings, parts after); a fiscal year's total dated before its parts; a zero total (counted: the filing says nothing is due).

- **Step 3. Near-miss listing.** `domains/analysis/debt_checks.py` and `python -m domains.analysis debt-checks [--ticker T] [--as-of D]`: for every balance date with a filed total, the parts at that date, which rule fired (#408 inside, #412 beside, #415 in place, none), and for "none" the ratio that came closest to each rule's line. Read-only, point-in-time (`as_of`). Tests on the fixture.

- **Step 4. Real data.** On the restored snapshot: `reproduce --all --rebuild` (every stored run reproduces to the cent and rebuilds as before through its own map); every stored run date of all eight companies built fresh with and without Step 1; list what moves (expected: Exxon only, dates reading 2019-12-31 or 2025-12-31). The near-miss listing for all eight companies goes into the results.

## Alternatives considered

- **Count the lease-inclusive current tag first for every company.** Coca-Cola's plain non-current with a lease-inclusive current would count current leases twice (once here, once through `FinanceLeaseLiability`), so the choice must follow the non-current tag.
- **A "total exceeds parts" note only** (the issue's option a). Says the gap without closing it; the filing gives the right figure, so read it.
- **Add the finance-lease total's current share.** Exxon doesn't tag `FinanceLeaseLiabilityCurrent`; the lease-inclusive current tag is the filing's own figure.

**Limits.** Exxon's FY2015–FY2017 year ends tag a plain non-current beside a larger lease-inclusive one, and no finance-lease line before 2021, so leases are missing there in both halves; runs read those years only as cost-of-debt history, and fixing them needs a third tag choice, left for a later item.

## Files to change

`domains/fundamentals/concept_map.csv`, `concept_maps/<new>.csv`, `concept_maps/CHANGES.md`, `domains/fundamentals/facts.py`; `domains/analysis/reading_rules.py` and `.md`; `domains/analysis/debt_checks.py`, `domains/analysis/__main__.py`; tests above; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8 value per share, Q4 cost of debt) and Q1–Q2 through the reported view's `net_debt`: fresh Exxon runs reading the 2019 or 2025 year end count $84M or $34M more debt. Nothing added to, renamed in or removed from any output; no new note, code or lesson. A run's `balance:debt_current` row can now name `LongTermDebtAndCapitalLeaseObligationsCurrent` beside a plain-looking current portion; the label stays "Porción corriente de la deuda". Runs record reading rules v9. The new `debt-checks` command is for the engine team, not the app.
