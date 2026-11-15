# Backlog #341: Caterpillar's current debt, counted as zero in every run

Issue: https://github.com/sonderbot-ar/warren/issues/341 (from the #197 design review) · Branch `backlog-341-cat-current-debt` · Status: design (nov.15.2026).

## Problem

Every one of the 113 stored Caterpillar (CAT) runs carries `balance_counted_zero` naming `debt_current`: the run reads CAT's current portion of long-term debt as zero.

- CAT's balance sheet line "Long-term debt due within one year" is `us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent` (already priority 2 for `debt_current`), but CAT files it **only by segment** on `srt:ProductOrServiceAxis` (Machinery, Energy & Transportation; Financial Products), never as a consolidated fact (FY2023 10-K, accession 0000018230-24-000009: 1,044M + 7,719M at 2023-12-31). Company facts drop dimensional facts, so the loader never sees it (`domains/fundamentals/known_gaps.csv` line 29).
- CAT's debt maturity note tags the consolidated total as `us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths` at every year end 2010 to 2025 (16 values in CAT's company facts). Where checked it equals the segment sum exactly: 8,763M at 2023-12-31 (1,044 + 7,719), 5,322M at 2022-12-31 (120 + 5,202).

**Effect.** Debt is short by $5bn to $9bn in every CAT run, so net debt is too low and value per share too high (the issue's trial, on a copy of the database: a fresh run as of 2026-10-30 reads $7.12bn current debt at 2025-12-31, debt $36.21bn → $43.33bn, value per share $218.45 → $205.62). The same zero also inflates operating working capital's liabilities (`math_engine._operating_nwc` subtracts `debt_current` from current liabilities), so CAT's working capital is understated by the same amount.

**What is already counted.** CAT's consolidated `debt_noncurrent` (`LongTermDebtNoncurrent`, year ends) and `short_term_borrowings` (year ends) both already include Cat Financial's debt. Only the current portion is missing. So today CAT is valued on consolidated cash flows and consolidated debt *minus one piece of it*: neither the consolidated view nor a finance-arm-excluded view.

## Why not a plain fallback for every company

Adding the tag as priority 3 for `debt_current` in the global map would also fill periods for three other companies (checked in each company's company facts, every period end from 2009 where priorities 1 and 2 are missing):

| Company | Period ends filled | Values | Problem |
|---|---|---|---|
| JNJ | 6 (2012-01-01 to 2019-12-29) | 7M to 2,104M | **Double count.** JNJ's "Loans and notes payable" (`ShortTermBorrowings`, already counted) includes the current portion of long-term debt: `DebtCurrent` ≈ `ShortTermBorrowings` at each of the six dates (e.g. 7,000M vs 7,004M at 2016-01-03). The maturity tag would add 2,104M on top. |
| AAPL | 3 (2013-09-28 to 2014-03-29) | 0 | Harmless but changes the counted-as-zero note into a counted zero. |
| MSFT | 2 (2010-06-30, 2011-06-30) | 0 | Same. |
| KO, PG, WMT, XOM | 0 | | |

The maturity tag is also principal, not carrying value (PG 2013: 4,083M principal against 4,506M on the balance sheet), so it is a fallback only where nothing better exists. So the tag must apply to CAT only.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. A map row can be limited to named companies (companies as data, Decision 11).**
  - `concept_map.csv` and `concept_map_reported.csv` gain a last column `companies`: empty means every company (every existing row), otherwise a `;`-separated list of tickers from `universe.csv`. `ConceptRow.companies: frozenset[str]` (empty = all).
  - `load_concept_map` accepts the new header, and the old 8-column header for the archived copies in `concept_maps/` (they read as `companies` empty, which is what they meant). Validation: every listed ticker is in `universe.csv`; a ticker list on a priority-1 row is refused (a company-only row is a fallback, never the item's first tag, so every other company keeps its own first tag); all rows of an item still share unit, period type, definition and gate.
  - `ingest.extract_facts` skips a fact whose row lists companies that don't include the ingested ticker (counted as `skipped["company_scope"]`). Nothing else changes: the facts table never holds the tag for another company, so every query, the quality report and `concept_map_in_force` work unchanged, and an archived map that doesn't list the tag never sees it.
  - New row: `debt_current, us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths, 3, …, companies=CAT`, note: CAT files the balance-sheet line only by segment; the maturity note's total equals the segment sum (two years checked); principal, not carrying value.
  - The map's copy in `concept_maps/` and its `CHANGES.md` line, in the same commit (`tests/fundamentals/test_concepts.py` requires it). `known_gaps.csv`: CAT `debt_current` narrows from every period to `Q1;Q2;Q3` ("[annual only] the maturity-note total is tagged only at year end; quarterly the balance-sheet line is by segment"), matching CAT's `debt_noncurrent` and `short_term_borrowings` rows.
  - Tests (`tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`): the shipped maps load and every archived copy still loads; a scoped row with an unknown ticker, or on priority 1, is refused; the old header loads as unscoped; `extract_facts` keeps a scoped tag's facts for a listed ticker and skips them, counted, for any other; the shipped map's only scoped row is the CAT one.
  - Exit: full suite and ruff clean; the fingerprint test passes with the new copy.

- **Step 2. Real data.** On the restored snapshot: `fundamentals ingest --all` (only CAT gains facts: 16 year-end values); `fundamentals quality` passes the gate; `reproduce --all` reproduces every stored run to the cent (each through its own map, v0.9.64); `reproduce --all --rebuild` compared with `main`: only CAT runs may move. List CAT's moved runs (debt, net debt, working capital, value per share before and after) and confirm the `balance_counted_zero` note no longer names `debt_current` on them. A run whose balance sheet is a quarter end reads the latest year end's value with the existing `balance_carried_forward` note, as CAT's non-current debt and short-term borrowings already do. Exit: no non-CAT run moves; every CAT run built after the change counts current debt.

## Alternatives considered

- **A global priority-3 fallback.** Double counts JNJ (table above).
- **Read the segment facts from the XBRL instance documents.** The right long-run answer for dimensional data, and needed for #233's split, but a new source and parser (an adapter, Decision 11) for one line. Not now.
- **A CAT-only rule in the engine.** Puts a company in code; the guardrail is companies as data.
- **Leave CAT's current debt out until #233 decides on Cat Financial.** Today's number is neither consolidated nor finance-arm-excluded; counting the missing piece makes it consistently consolidated, which matches the consolidated cash flows Warren forecasts. Splitting the finance arm out (debt and its cash flows together) stays #233.

## Files to change

`domains/fundamentals/concepts.py`, `domains/fundamentals/ingest.py`, `domains/fundamentals/concept_map.csv`, `concept_map_reported.csv`, `concept_maps/<new sha>.csv` and `CHANGES.md`, `domains/fundamentals/known_gaps.csv`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8, value per share): every fresh CAT run counts its current debt, so its net debt, working capital and value per share are right on the consolidated view. Fresh CAT runs move (Step 2 gives the numbers); stored runs keep their rows. A CAT run loses `debt_current` from its `balance_counted_zero` note and, when its balance sheet is a quarter end, gains `debt_current` in `balance_carried_forward`. A CAT run's `debt` source now cites the 10-K's maturity-note fact. No code, note, param or lesson is added, renamed or removed.
