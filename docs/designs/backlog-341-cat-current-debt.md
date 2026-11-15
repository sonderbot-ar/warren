# Backlog #341: Caterpillar's current debt, counted as zero in every run

Issue: https://github.com/sonderbot-ar/warren/issues/341 (from the #197 design review) · Branch `backlog-341-cat-current-debt` · Status: design (nov.15.2026).

## Problem

Every one of the 113 stored Caterpillar (CAT) runs carries `balance_counted_zero` naming `debt_current`: the run reads CAT's current portion of long-term debt as zero.

- CAT's balance sheet line "Long-term debt due within one year" is `us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent` (already priority 2 for `debt_current`), but CAT files it **only by segment** on `srt:ProductOrServiceAxis` (Machinery, Energy & Transportation; Financial Products), never as a consolidated fact (FY2023 10-K, accession 0000018230-24-000009: 1,044M + 7,719M at 2023-12-31). Company facts drop dimensional facts, so the loader never sees it (`domains/fundamentals/known_gaps.csv` line 29).
- CAT's debt maturity note tags the consolidated total as `us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths` at every year end 2010 to 2025 (16 values in CAT's company facts). Where checked it equals the segment sum exactly: 8,763M at 2023-12-31 (1,044 + 7,719), 5,322M at 2022-12-31 (120 + 5,202).

**Effect.** Debt is short by $5bn to $9bn in every CAT run, so net debt is too low and value per share too high (the issue's trial, on a copy of the database: a fresh run as of 2026-10-30 reads $7.12bn current debt at 2025-12-31, debt $36.21bn → $43.33bn, value per share $218.45 → $205.62). The same zero also inflates operating working capital's liabilities (`math_engine._operating_nwc` subtracts `debt_current` from current liabilities), so CAT's working capital is understated by the same amount.

**What is already counted.** CAT's consolidated `debt_noncurrent` (`LongTermDebtNoncurrent`, year ends) and `short_term_borrowings` (year ends) both already include Cat Financial's debt. Only the current portion is missing. So today CAT is valued on consolidated cash flows and consolidated debt *minus one piece of it*: neither the consolidated view nor a finance-arm-excluded view. This change makes CAT's debt *complete on the consolidated view*. It does not make the consolidated view right for CAT: consolidated figures mix Cat Financial's lending book (its finance receivables in working capital, its debt in net debt, its interest in operating costs) with the machinery business, which is why Koller, Goedhart and Wessels and Damodaran value a captive finance arm separately. That split is #233.

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
  - `ingest.extract_facts` (its `IngestResult` carries the ticker) skips a fact whose row lists companies that don't include the ingested ticker (counted as `skipped["company_scope"]`). Nothing else changes: the facts table never holds the tag for another company, so every query, the quality report and `concept_map_in_force` work unchanged, and an archived map that doesn't list the tag never sees it.
  - New row: `debt_current, us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths, 3`, with the item's existing unit, period type, gate and definition (the loader requires them shared), `companies=CAT`, note: CAT files the balance-sheet line only by segment; the maturity note's total equals the segment sum (two years checked); principal, not carrying value.
  - `concept_map_in_force(conn, sha256, ticker)`: a rebuild through an *older* map leaves out that map's rows limited to other companies, because a later map that widened a row may have stored other companies' facts under the tag (explainer, point 4). A test pins that a row's companies only ever widen across map versions, so today's map, read without a filter, never sees a fact its scope excludes. `runs.rebuild` passes the run's ticker. The `concepts` table holds no scope column: scope is enforced where facts enter (ingest) and in the archived view.
  - `domains/analysis/reading_rules.md` gets a row under the same version 5: which figures a run reads is pinned by the map's fingerprint, not the rules version, so the brief's "same rules, different map fingerprints" case (brief line 108) is the one a student sees beside an older CAT run (product lead).
  - The map's copy in `concept_maps/` and its `CHANGES.md` line, in the same commit (`tests/fundamentals/test_concepts.py` requires it). `known_gaps.csv`: CAT `debt_current` narrows from every period to `Q1;Q2;Q3` ("[annual only] the maturity-note total is tagged only at year end; quarterly the balance-sheet line is by segment"), matching CAT's `debt_noncurrent` and `short_term_borrowings` rows.
  - Tests (`tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`): the shipped maps load and every archived copy still loads; a scoped row with an unknown ticker, or on priority 1, is refused; the old header loads as unscoped; `extract_facts` keeps a scoped tag's facts for a listed ticker and skips them, counted, for any other; the shipped map's only scoped row is the CAT one.
  - Exit: full suite and ruff clean; the fingerprint test passes with the new copy.

- **Step 2. Real data.** On the restored snapshot: `fundamentals ingest --all` (every company, so no fresh run carries the `concept_map_changed` note, `math_engine.py`; only CAT gains facts: 16 year-end values); `fundamentals quality` passes the gate; `reproduce --all` reproduces every stored run to the cent (each through its own map, v0.9.64); `reproduce --all --rebuild` compared with `main`: only CAT runs may move. List CAT's moved runs (debt, cost of debt, WACC, `nwc_pct`, value per share before and after; analyst) and confirm the `balance_counted_zero` note no longer names `debt_current` on them. A run whose balance sheet is a quarter end reads the latest year end's value with the existing `balance_carried_forward` note, as CAT's non-current debt and short-term borrowings already do. Exit: no non-CAT run moves; every CAT run built after the change counts current debt.

## What else moves on a CAT run (analyst)

- **Working capital.** `_operating_nwc` takes `debt_current` out of current liabilities, so CAT's working capital rises by the current debt and `nwc_pct` goes from about 16% to about 27% of revenue (run `CAT_2026-10-30_1`), raising the forecast's working-capital investment about 70% a quarter for the five forecast years (the terminal value has no working-capital term). Today's zero also lets year-to-year swings in current debt (9,149 → 6,352 → 5,322 → 8,763M) leak into the working-capital change; the fix removes that noise. The 27% includes Cat Financial's current finance receivables, which is the consolidated view (#233).
- **Cost of debt and WACC.** `_cost_of_debt` divides interest by average debt at the two year ends, so more debt gives a lower cost of debt (about 5.4% → 4.5%) and a higher debt weight. That is why value per share falls less than the added debt per share.

## Alternatives considered

- **A global priority-3 fallback.** Double counts JNJ (table above).
- **Read the segment facts from the XBRL instance documents.** The right long-run answer for dimensional data, and needed for #233's split, but a new source and parser (an adapter, Decision 11) for one line. Not now.
- **A CAT-only rule in the engine.** Puts a company in code; the guardrail is companies as data.
- **Leave CAT's current debt out until #233 decides on Cat Financial.** Today's number is neither consolidated nor finance-arm-excluded; counting the missing piece makes it consistently consolidated, which matches the consolidated cash flows Warren forecasts. Splitting the finance arm out (debt and its cash flows together) stays #233.

## Design review (nov.15.2026)

- **Analyst, GO, no blockers.** Checked the tag against the balance sheet's two segment lines for two more years: FY2024 46 + 6,619 = 6,665 (0000018230-25-000008), FY2025 35 + 7,085 = 7,120 (0000018230-26-000008); FY2025's non-current segment lines add to the `LongTermDebtNoncurrent` Warren already counts, so the new piece is on the same basis. JNJ double count confirmed. Taken: the working-capital, cost-of-debt and WACC effects (section above) and Step 2's columns. Found a separate, existing problem: JNJ's `LongTermDebtCurrent` at three year ends (2016 to 2018) is already inside its `ShortTermBorrowings`, so 87 stored JNJ runs overstate debt by $1.5bn to $2.6bn: filed as a backlog issue, not this PR's scope. Idea not taken: refuse a scoped row where a higher-priority fact exists at the same date (the priority order already picks the higher one; a CAT switch to a consolidated balance-sheet tag would simply win).
- **Professor, GO, no blockers.** Defensible as a stopgap: neither Koller nor Damodaran argues for half-counting. Taken: the claim is "complete consolidated debt", not "a consistent valuation of CAT" (Problem). Ideas filed on #233: a run note on CAT runs saying debt includes the finance arm's borrowings and the arm is not valued separately; value Cat Financial on cash flow to equity; a lesson on captive finance arms. The principal-vs-carrying gap for CAT was not checked separately; the analyst's segment sums match the balance sheet's own lines, so for CAT the two agree at the four year ends checked.
- **Explainer.** Eight gaps. Taken: the row's shared fields, how the ticker reaches ingest, the archived-map scope (now filtered, above), the re-ingest before runs, Step 2's rebuild meaning (stored rows reproduce; `--rebuild` recomputes with today's code through each run's own map). The 370-day carry-forward limit is unchanged and applies as it does to CAT's other year-end debt items.
- **Product lead, no blocking objection.** Taken: the rules version stays 5 (above); the team-sync entry lists the moved runs' before and after.

## Files to change

`domains/fundamentals/concepts.py`, `domains/fundamentals/ingest.py`, `domains/analysis/runs.py` (passes the ticker), `domains/analysis/reading_rules.md`, `tests/analysis/test_runs.py` (the #357 map-edit tests now widen the CAT row instead of adding it), `domains/fundamentals/concept_map.csv`, `concept_map_reported.csv`, `concept_maps/<new sha>.csv` and `CHANGES.md`, `domains/fundamentals/known_gaps.csv`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8, value per share): every fresh CAT run counts its current debt, so its net debt, working capital and value per share are right on the consolidated view. Fresh CAT runs move (Step 2 gives the numbers); stored runs keep their rows. A CAT run loses `debt_current` from its `balance_counted_zero` note and, when its balance sheet is a quarter end, gains `debt_current` in `balance_carried_forward`. A CAT run's `debt` source now cites the 10-K's maturity-note fact. `reading_rules_version` stays 5, so beside an older CAT run of the same date the app shows the brief's "different map fingerprints" case (brief line 108): the fresh run uses the corrected reading. No code, note, param or lesson is added, renamed or removed. The working-capital ratio, cost of debt and WACC of fresh CAT runs move too (Step 2).
