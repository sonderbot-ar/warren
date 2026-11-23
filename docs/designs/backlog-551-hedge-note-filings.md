# Backlog #551: the hedge note names its evidence filings, so the app can link them

Issue: https://github.com/sonderbot-ar/warren/issues/551 (from the #547 review, front-end ask) · Branch `backlog-551-hedge-note-filings` · Version v0.10.37 when merged.

Status: In progress (nov.23.2026).

## Problem

The `interest_net_of_hedge_gains` note (backlog #542, v0.10.35) tells a student that J&J's interest line is net of what its currency swaps earn. The filings that prove it are named only inside the free-text `evidence` column of `domains/analysis/interest_caveats.csv` (the FY2018, FY2019, FY2021 and FY2025 10-Ks' derivatives tables). The note's params carry the stated rate's own filing (`effective_rate_filing`) but not these, so the app's *Fuente* panel cannot link the filings behind the claim itself.

## Plan

**Step 0. This doc.**

**Step 1. The caveat's accession numbers, and the note's `evidence_filings`.**

- `InterestCaveat.accessions` (a property, so the row's fields and constructor are unchanged): every SEC accession number in `evidence` (pattern `\d{10}-\d{2}-\d{6}`), in the order written, each once. The shipped J&J row gives `0000200406-19-000009`, `0000200406-20-000010`, `0000200406-22-000022`, `0000200406-26-000016`.
- The note gains one param, `evidence_filings`: a list of filings, each the same shape as a part's `filing` and `effective_rate_filing` (`inputs._filing`: `accession_no`, `form`, `filed_at`, `url`), in the data file's order.
- Point-in-time: a filing is listed only when Warren's facts know its filing date and that date is on or before the run's `as_of` (the same `filed_at <= as_of` rule `_effective_rate` uses). So a run as of 2020 lists the FY2018 and FY2019 10-Ks and never the FY2021 or FY2025 ones, and an accession Warren has never ingested is left out rather than shown without a date. The list can be empty (an early run, or a row whose evidence names no accession); the note and its text are unchanged either way.
- The English text does not change, so no stored answer's wording moves.
- The loader stays as it is: `evidence` must not be empty (its existing check). A row whose evidence names no accession is still valid; it lists none.
- Tests:
  - `tests/analysis/test_interest_caveats.py`: the shipped row's `accessions` are the four J&J 10-Ks in order; repeats are listed once; evidence with no accession gives an empty tuple; the empty-evidence check still fails.
  - `tests/analysis/test_single_values.py` (Test Corp with a caveat for TST): evidence naming a 10-K filed before `as_of`, one filed after it, and one Warren never ingested lists only the first, with its form, date and url; no listed filing is dated after `as_of`; evidence with no accession gives `[]`.
- Exit: the new tests fail on `main` and pass here; full suite, `ruff check` and `ruff format --check` green.

**Step 2. Real data.** On the restored snapshot: the newest J&J run's cost-of-debt notes list all four 10-Ks with their dates; a J&J run as of 2020 lists only the two filed by then; `reproduce --all` unchanged (no stored number moves).

## Alternatives considered

- **Split `evidence` into a separate `accessions` column.** Cleaner to read, but it changes the file's columns and every test fixture for no gain: the accession numbers are already in the text, in a fixed SEC format, and one regex reads them. Rejected for now; worth it if a second caveat row arrives with accessions that need no prose.
- **List every named filing, whatever its date.** The caveat is a fact about J&J's accounting, but a student's answer as of 2020 must not link a 2026 filing (the point-in-time rule). Rejected.
- **Make an accession in the evidence mandatory in the loader.** Useful, but it would refuse the existing test fixtures' free-text evidence for a rule the app does not need; the app handles an empty list. Left as is.

## Files to change

- `domains/analysis/interest_caveats.py` (the `accessions` property)
- `domains/analysis/single_values.py` (`_hedge_note`'s new param)
- `tests/analysis/test_interest_caveats.py`, `tests/analysis/test_single_values.py`
- `docs/designs/backlog-551-hedge-note-filings.md`; on merge `docs/versions.md`, `docs/team-sync.md`

## Product impact

- Serves the brief's sources rule (every figure and claim links its filing, *Fuente*) for brief Q3 on J&J's cost of debt.
- Adds one param, `evidence_filings`, to the `interest_net_of_hedge_gains` note on the cost-of-debt chart points and cell. Nothing is renamed or removed; the text catalogue needs no new string, since the panel lists filings as it does for parts.
