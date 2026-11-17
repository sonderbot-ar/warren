# Backlog #421: the current portion read on the same basis as the non-current debt

Issue: https://github.com/sonderbot-ar/warren/issues/421 (from the #415 design and gatekeeper reviews), items 1 to 3 · Branch `backlog-421-current-lease-debt` · Version v0.9.81, merged nov.16.2026 (PR #425, merge `997eb1f`, after CI green and a gatekeeper GO). Item 4 is an app idea for the front-end team and stays open.

## Problem

1. **Exxon's current finance-lease debt is never counted.** Exxon tags its non-current debt only as `LongTermDebtAndCapitalLeaseObligations` (lease-inclusive, map `debt_noncurrent` priority 2), so D3 skips the finance-lease line (`math_engine._lease_inclusive`, "finance leases skipped: the debt tag already includes them"). Its current portion is tagged twice in the 10-K: `LongTermDebtCurrent` (debt only, `debt_current` priority 1) and `LongTermDebtAndCapitalLeaseObligationsCurrent` (debt and the current finance-lease portion, priority 2). Priority 1 wins, so the current lease portion falls between the two: counted neither in the current portion nor through the lease line. Exxon's year ends in Warren's data (latest filing, millions):

   | Year end | `LongTermDebtCurrent` | `…AndCapitalLeaseObligationsCurrent` | Gap |
   |---|---|---|---|
   | 2018-12-31 | 4,070 | 4,070 | 0 |
   | 2019-12-31 | 1,617 | 1,701 | 84 |
   | 2020-12-31 to 2024-12-31 | equal | equal | 0 |
   | 2025-12-31 | 6,200 | 6,234 | 34 |
   | 2010-12-31 | 345 | 12,227 | (the long-term debt again, under the wrong tag, in a 10-Q of 2011-05-05) |

   At 2019-12-31 the 84M is the current finance-lease portion: the 10-K's lease note puts 84M of "lease liability due within one year" in notes and loans payable, and the filing's own total adds up only with the lease-inclusive figure (bank loans 316 + commercial paper 18,561 + 1,701 = 20,578 = `DebtCurrent`; with 1,617 it is 20,494). At 2025-12-31 the 34M is a rounding: `LongTermDebtCurrent` is the debt note's "$6.2 billion" (inline XBRL scale 9, decimals −8), and 3 + 3,059 + 6,234 = 9,296 = `DebtCurrent`. In the equal years (2020 to 2024) the plain tag already holds the leases (117M of finance leases at 2024-12-31, both tags 4,892M). (Analyst, design review.) The only other company that tags both current tags at one date is Coca-Cola at 2023-12-31, where they are equal and its non-current tag is the plain one. So the effect is small: Exxon's runs whose balance date, history year or cost-of-debt year end is 2019-12-31 or 2025-12-31, by $84M or $34M. It matters because the rule should hold by construction: when the non-current debt includes leases, the current debt must too, or the leases due within a year disappear.

2. **A point-in-time test is missing for #415's rule.** P&G's FY2009 parts (balance date 2009-06-30) were first filed 2010-08-13; its total was filed 2009-10-29. A history read between those dates must count the total, and after 2010-08-13 the parts.

3. **The debt rules' measurements don't list near-misses**: balance dates with a filed total where #408, #412 or #415 did not fire, and how close each came (Exxon 2011-03-31 was found by hand).

## Plan

- **Step 0.** This design doc.

- **Step 1. The current portion on the non-current debt's basis.**
  - Concept map: `us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent` moves from `debt_current` priority 2 to a new optional item `debt_current_with_leases` (priority 1); `debt_current` keeps `LongTermDebtCurrent` (1) and CAT's maturities tag (now 2). New map copy in `concept_maps/` and its line in `CHANGES.md`. No re-ingest: facts are stored by tag and a tag may change item (`sync_concepts`).
  - `domains/fundamentals/facts.get_facts`: when `debt_current` is asked and the map in force has `debt_current_with_leases`, both items and `debt_noncurrent` are read and merged into `debt_current` per balance date (`_current_on_noncurrent_basis`), so every reader (the engine's history, the annual check, the reported view) sees one current portion:
    - only one of the two tags at a date: that one (as before: the lease-inclusive tag was the fallback);
    - both: the lease-inclusive one when the same date's `debt_noncurrent` is lease-inclusive (by its tag name: `CapitalLease` or `FinanceLease`, as `math_engine._lease_inclusive` already reads it), the lease-inclusive figure is above the plain one (equal figures keep the plain tag, which then already holds any leases), and it is not equal to the same date's non-current debt; otherwise the plain one. The last test is the signature of Exxon's mis-tags (12,227M at 2010-12-31 beside a plain 345M, 12,316M at 2011-03-31, each equal to the non-current debt); a ratio bound (first draft: 1.5 times the plain figure) would also drop a real lease portion beside a small current portion (Exxon's was 181M at 2022-12-31).
    - only the plain tag at a date, whatever the non-current tag: the plain one (nothing else is filed).
    - `debt_current_with_leases` and `debt_noncurrent` are returned only if asked.
  - A map without the new item (every stored run's) reads exactly what it read before: the merge is skipped and the tag is still `debt_current` priority 2 there.
  - `READING_RULES_VERSION` 8 → 9 with its row in `reading_rules.md`.
  - No new run note: the debt row's method already names the tag (`LongTermDebtAndCapitalLeaseObligationsCurrent`) and the run already carries "finance leases skipped: the debt tag already includes them".
  - The merged fact is named `debt_current` and keeps the tag, value and filing (accession) of the figure chosen, so the row's method names `LongTermDebtAndCapitalLeaseObligationsCurrent` when that one is read. "The map in force" is today's map for a fresh run and the run's own archived map for a rebuild (`concept_map_in_force`, #357).
  - CAT's maturities tag moves from `debt_current` priority 3 to 2 (the loader allows no gaps); it is CAT-only and CAT never tags the lease-inclusive current, so nothing CAT reads changes. `test_the_shipped_maps_scope_only_caterpillars_maturity_note_total` names the new priority.
  - Tests (`tests/analysis/test_current_lease_debt.py`): both tags with a lease-inclusive non-current → the larger counts in debt, working capital and the cost of debt; a plain non-current → the plain current; only the lease-inclusive tag → it (the old fallback); a lease-inclusive figure equal to, below the plain one, or equal to the non-current debt → the plain one; a lease portion near the size of a small current portion is kept; Exxon 2019-12-31 adds up to its own total; the merged fact is named `debt_current`; through #408's map (`c621cb3eaf6e`) the run reads what it read before.
  - Exit: full suite and ruff clean.

- **Step 2. Tests the #415 reviews asked for** (`tests/analysis/test_debt_current_total_in_place.py`). P&G FY2009 point in time: the total filed first, the parts first filed as the next annual report's comparative; a history read the day before the parts' filing counts the total, one on the filing day itself counts the parts (a filing is public on its filing date). A fiscal year's total dated before its parts is not used. A zero total is counted (the filing says nothing is due) in place of older parts.

- **Step 3. Near-miss listing.** `domains/analysis/debt_checks.py` and `python -m domains.analysis debt-checks [--ticker T] [--as-of D] [--near-misses]` (default: every company, the last ended New York day): for every balance date with a filed total, the parts filed for that same date, which rule fired (`inside`: #408, the current portion already inside short-term borrowings; `beside`: #412, commercial paper a line of its own; `in_place`: #415, the total counted in place of older parts), the gap between the total and the same-date parts, and the largest part as a multiple of the total (#415's mis-tag line is 1.5×). A near miss is a date where no rule fired, some part is filed, and the gap is over 1% of the total (a total rounded to a tenth of a billion, as JNJ's, stays inside). Read-only, point-in-time. Tests on the fixture.

- **Step 4. Real data.** On the restored snapshot: `reproduce --all --rebuild` (every stored run reproduces to the cent and rebuilds as before through its own map); every stored run (not the what-ifs) built fresh twice in memory, same pinned market data and choices, through #408's map (`c621cb3eaf6e`, which is exactly the old reading) and through today's; list what moves, value per share, and any run-note code that appears or disappears (product lead: #408's and #412's notes test their lines against the total, so a larger current portion could make one fire or stop). Expected: Exxon only, dates reading 2019-12-31 or 2025-12-31. The near-miss listing for all eight companies goes into the results.

## Alternatives considered

- **Count the lease-inclusive current tag first for every company.** Coca-Cola's plain non-current with a lease-inclusive current would count current leases twice (once here, once through `FinanceLeaseLiability`), so the choice must follow the non-current tag.
- **A "total exceeds parts" note only** (the issue's option a). Says the gap without closing it; the filing gives the right figure, so read it.
- **Add the finance-lease total's current share.** Exxon tags `FinanceLeaseLiabilityCurrent` only by lease type (dimensional), which company facts drop; the lease-inclusive current tag is the filing's own figure.

**Limits.** A rounded plain figure above a precise lease-inclusive one (say 6.2bn beside 6,180M) keeps the rounded one; no fact does this today (analyst). Exxon's FY2015–FY2017 year ends tag a plain non-current beside a larger lease-inclusive one, and no finance-lease line before 2021, so leases are missing there in both halves; runs read those years only as cost-of-debt history, and fixing them needs a third tag choice, left for a later item.

## Design review (nov.16.2026)

- **Analyst, GO, no blockers.** Practitioner reading confirmed from the 2019 and 2025 10-Ks (the totals add up only with the lease-inclusive figure). Taken: the 2025 gap is a rounding and the equal years already hold leases (Problem corrected); the mis-tag guard is "equal to the non-current debt" in place of the 1.5× bound, which would drop a real lease portion beside a small current portion; the Exxon 2019 add-up test; the `FinanceLeaseLiabilityCurrent` wording. Noted as a limit: a rounded plain figure can still win. Only KO and XOM tag the lease-inclusive current: KO's 2024+ quarter ends tag it alone (read as before), KO 2023-12-31 has both equal; Exxon's quarter ends tag neither (only the total, #415).
- **Professor, GO, no blockers.** Koller, Goedhart and Wessels, Damodaran and Penman count lease obligations as debt whatever their maturity; ASC 842-20-45-1 has the filer say which line holds finance leases, which supports reading its own lease-inclusive current figure. Taken for the lesson: the mis-tag guard is a data check, not a valuation rule; Exxon's FY2015–FY2017 lease gap stays. Not taken: words on the debt row's method (the row already names the tag and the run already says the lease line is skipped because the debt tags hold leases; a sentence there would change every Exxon run's method text for a figure that moves on two dates).
- **Explainer.** Gaps taken: "it" in the bound (now gone), the tag-name test, a lone plain current, the map in force, CAT's priority and `sync_concepts`, the merged fact's filing, the filing day itself, the zero total, the rule names and the near-miss line, the command's defaults, what is built in Step 4, the FY2015–FY2017 limit. Not taken: glosses of #408, #412, #415 and the brief's questions (their docs explain them).
- **Product lead, one blocker, taken.** Step 4 lists the run-note codes that appear or disappear on Exxon's 2019 and 2025 year ends, and the results say so. Ideas for the app (a side-panel sentence when the debt row's tag is lease-inclusive; the FY2015–FY2017 limit in the brief) go to team-sync.

## Results (Step 4, nov.16.2026)

On the restored snapshot (`warren-20261116T053654Z`; no ingest needed: facts are stored by tag, and the map only moves one tag to a new item).

- **Stored runs.** `reproduce --all --rebuild`: 903 of 903 reproduced to the cent; 692 of 903 rebuilt to identical rows, the same count as on `main`; the other 211 were made by older code and differ as before. No stored run moves: each rebuilds through its own map, where the lease-inclusive tag is still `debt_current` priority 2.
- **Fresh runs.** All 903 stored run dates built twice in memory (same pinned market data and choices), through #408's map and through today's; none refused, none stored. **Only Exxon moves, on 44 dates, and by at most 0.03% of value per share.** No run-note code appears or disappears on any date (the product lead's check), so #408's and #412's notes fire exactly as before.
  - 4 runs (2020-03-01 to 2020-05-01) read the 2019-12-31 balance sheet: debt $46,836M → $46,920M (+84M), value per share +0.01% to +0.02% (e.g. 2020-04-01 $99.83 → $99.85).
  - 39 runs (2020-06-01 to 2023-02-01) read FY2019 only as history: that year's working capital and the working-capital forecast move, and the cost of debt where FY2019 is in its window; debt unchanged; value per share within ±0.03% (2021-03-01 $4.87 → $4.88, where equity is small).
  - 1 run (2026-10-30) reads FY2025 as history: $115.34 → $115.35.
  - Apple, Microsoft, Coca-Cola, Johnson & Johnson, Procter & Gamble, Caterpillar and Walmart: nothing moves on any date.
- **Near misses** (`debt-checks --as-of 2026-11-15 --near-misses`): 155 balance dates carry a filed total (JNJ 16, P&G 70, Exxon 69); 11 are near misses.
  - **P&G year ends 2009, 2013–2016, 2019–2022:** the total is above the same-date current portion + commercial paper by 98M to 481M (2009: 4,352M, the year its short-term borrowings were not tagged). P&G's debt note has a third line of short-term debt (other short-term borrowings, not tagged under a mapped concept), so year-end P&G runs undercount debt due within a year by about 1% to 4% of it. Filed as a follow-up.
  - **JNJ 2014-12-28:** total 3,600M, short-term borrowings 3,638M (rounded total, 1.0%); not a real miss.
  - **Exxon 2009-12-31:** parts 1,592M against a total of 2,476M (the issue's item 1, before 2011; not runnable, `SUPPORTED_FROM`).
  - Exxon's 2019-12-31 and 2025-12-31 are no longer near misses: the parts now add up to the total.

## Gatekeeper (nov.16.2026)

GO, no blockers: 2,424 passed, 10 skipped; ruff check and format clean; point-in-time holds (the merge only chooses among facts the as-of query already returned); a map without the new item reads what it read before (`XOM_2020-04-01_1` rebuilds with the same differences on this branch and on `main`); no duplicate `debt_current` period on any company, mode or frequency; the test's priority 3 → 2 follows the map; fingerprint `04a7c2600421` matches v9; the map copy is byte-identical. Ideas (pairing the two tags on dates alone, with a guard against two fiscal labels at one date; the merged list's order) filed as a backlog issue; the P&G near misses are #426.

## Files to change

`domains/fundamentals/concept_map.csv`, `concept_maps/52635076391a….csv`, `concept_maps/CHANGES.md`, `domains/fundamentals/facts.py`; `domains/analysis/reading_rules.py` and `.md`; `domains/analysis/debt_checks.py`, `domains/analysis/__main__.py`; `tests/analysis/test_current_lease_debt.py`, `tests/analysis/test_debt_current_total_in_place.py`, `tests/analysis/test_debt_checks.py`, `tests/fundamentals/test_concepts.py` (one expected priority); on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8 value per share, Q4 cost of debt) and Q1–Q2 through the reported view's `net_debt`: fresh Exxon runs reading the 2019 or 2025 year end (as their balance sheet, a history year's working capital or a cost-of-debt year end) count $84M or $34M more current debt. Nothing added to, renamed in or removed from any output; no new note, code or lesson. A run's `balance:debt_current` row can now name `LongTermDebtAndCapitalLeaseObligationsCurrent` beside a plain-looking current portion; the label stays "Porción corriente de la deuda". Runs record reading rules v9. The new `debt-checks` command is for the engine team, not the app.
