# Backlog #558: each J&J filing the hedge note links holds the figures quoted beside it

Issue: https://github.com/sonderbot-ar/warren/issues/558 (from the analyst's design review of #551) · Branch `backlog-558-jnj-evidence` · Version v0.10.42 when merged.

Status: In progress (nov.24.2026).

## Problem

Since v0.10.37 (#551) the app links every filing named in the J&J row of `domains/analysis/interest_caveats.csv` (`evidence_filings` on the `interest_net_of_hedge_gains` note). The row's evidence said "The same table in the FY2019, FY2021 and FY2025 10-Ks (0000200406-20-000010, …): 153 + 370 (FY2020), …". No FY2019 figure was quoted, and the FY2020 figures come from the FY2021 10-K. A run as of 2020 links the FY2018 and FY2019 10-Ks only, so a student who opens the FY2019 10-K looks for 153 + 370 and does not find it.

## Plan

**Step 0. This doc.**

**Step 1. Quote each filing's own figures, and a test that keeps it so.**

- Read the derivatives note's table of hedge effects ("summary of the activity related to derivatives and hedges … net of tax", column "Interest (Income) Expense") in each 10-K on sec.gov, nov.24.2026:
  - FY2019 10-K (0000200406-20-000010, filed 2020-02-18): net investment hedge, amount excluded from effectiveness testing, 159 (FY2019), 56 (FY2018); cross-currency swaps reclassified from AOCI, 292 (FY2019), 133 (FY2018). So FY2019 is 159 + 292, and FY2018 matches the 56 + 133 the row already quotes from the FY2018 10-K.
  - FY2021 10-K (0000200406-22-000022): 174 + 402 (FY2021), 153 + 370 (FY2020). Unchanged.
  - FY2025 10-K (0000200406-26-000016): 193 + 326 (FY2025), 148 + 247 (FY2024). Unchanged.
- Reword the evidence so each figure follows the filing it comes from: "The same table, each figure from the filing named before it: FY2019 10-K (…20-000010): 159 + 292 (FY2019); FY2021 10-K (…22-000022): 153 + 370 (FY2020), 174 + 402 (FY2021); FY2025 10-K (…26-000016): 148 + 247 (FY2024), 193 + 326 (FY2025)". The accession order is unchanged, so `accessions` and `evidence_filings` give the same list.
- Test (`tests/analysis/test_interest_caveats.py`): after each accession, up to the next one, at least one "(FYyyyy)" figure appears, and every such year is the filing's own fiscal year or the one before (a 10-K's table shows two years). It fails on `main` (the FY2019 10-K is followed by no figure of its own) and passes here. `test_the_shipped_rows_accessions_are_its_four_10ks_in_order` stays green.
- Exit: the new test fails on `main` and passes here; full suite, `ruff check` and `ruff format --check` green.

No real-data step: only the free-text `evidence` changes. No code reads it except for its accession numbers, which are the same and in the same order; no number, note param or note text moves, and no stored run changes.

## Alternatives considered

- **Drop the FY2019 10-K from the evidence.** Rejected: a 2020 run would then link only the FY2018 10-K, and the FY2019 one is the newest filing such a run can check.
- **Store figures in their own columns.** Rejected for now: one company, one row; the free text plus a structural test is enough. If a second company joins the file, revisit.

## Review

A data-file wording fix with no method change, so the design review is the analyst alone (does each figure match its filing); the explainer and professor have nothing to judge here. The gatekeeper reviews the PR.

Analyst (nov.24.2026): GO; every quoted figure matches its filing on EDGAR. Two objections accepted: the FY2018 10-K's table heading does not say "net of tax" (the later three do), so the row now says so instead of calling it net of tax; and the test computes a filing's fiscal year from its accession (filed year minus one) rather than a hard-coded map. One noted, no change: the table rows say "gain or (loss)" and the row says "gains", which holds since every quoted J&J amount is positive.

## Files to change

- `domains/analysis/interest_caveats.csv` (the J&J row's `evidence`)
- `tests/analysis/test_interest_caveats.py`
- `docs/designs/backlog-558-jnj-evidence.md` (this doc)

## Product impact

Serves brief Q3, Q4 and Q8 for J&J, where the hedge note shows: the filings the app links now hold the figures quoted beside them. No output, code, param or text is added, renamed or removed; nothing changes on screen unless the app shows the evidence text, which it does not today.
