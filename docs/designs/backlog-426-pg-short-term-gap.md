# Backlog #426: P&G's "other" short-term borrowings, the missing part of its debt due within a year

Issue: https://github.com/sonderbot-ar/warren/issues/426 (found by #421's near-miss listing, `docs/designs/backlog-421-current-lease-debt.md`, Step 4) · Branch `backlog-426-pg-short-term-gap` · Version v0.9.83 on merge.

## Problem

At P&G's fiscal year ends (June 30) the 10-K tags its own total of debt due within one year (`us-gaap:DebtCurrent`, map item `debt_current_total`, read only as a check) and, in the debt note, its parts. Warren counts two of them, the current portion of long-term debt (`LongTermDebtCurrent`) and commercial paper (`CommercialPaper`), and the total is above their sum at every year end (`python -m domains.analysis debt-checks --ticker PG`, on the restored snapshot `warren-20261116T053654Z`):

| Year end | Total | Current portion | Commercial paper | Gap | `OtherShortTermBorrowings`, same 10-K |
|---|---|---|---|---|---|
| 2009-06-30 | 16,320M | 6,941M | 5,027M | 4,352M | 4,352M (FY2010 10-K, 0001193125-10-188769) |
| 2013-06-30 | 12,432M | 4,506M | 7,642M | 284M | 284M (0000080424-13-000063) |
| 2014-06-30 | 15,606M | 4,307M | 10,818M | 481M | 481M (0000080424-14-000057) |
| 2015-06-30 | 12,018M | 2,772M | 8,807M | 439M | 439M (0000080424-16-000212; 442M against 12,021M in the FY2015 10-K) |
| 2016-06-30 | 11,653M | 2,760M | 8,690M | 203M | 203M |
| 2019-06-30 | 9,697M | 3,388M | 6,183M | 126M | 126M (0000080424-19-000050) |
| 2020-06-30 | 11,183M | 2,508M | 8,545M | 130M | 130M |
| 2021-06-30 | 8,889M | 3,620M | 5,171M | 98M | 98M (0000080424-21-000100) |
| 2022-06-30 | 8,645M | 3,647M | 4,805M | 193M | 193M |
| 2010–2012, 2023–2026 | | | | 2M to 70M | 70, 37, 41, 42, 26, 27, 3M (2025 and 2026 within 1M of the gap: the parts are rounded to the million) |

**The missing line is tagged.** P&G's debt note lists a third short-term line, "Other" (bank loans and other short-term borrowings), and tags it `us-gaap:OtherShortTermBorrowings` at every year end from 2009 to 2026 (company facts, the 10-K of each year and its successor). The gap equals that figure at every one of these year ends, exactly or within 1M. The concept map doesn't read the tag, so a P&G run whose balance date is a year end undercounts its debt due within a year by 1% to 4%, and every P&G run's history years (working capital, the cost of debt) read the year ends without it.

At 2017-06-30 and 2018-06-30 P&G also tags short-term bank loans (`ShortTermBankLoansAndNotesPayable`, map `short_term_borrowings` priority 2: 0 and 800M) beside "other" (173M and 90M), and the total holds all four lines (2018: 1,772 + 800 + 7,761 + 90 = 10,423M). The FY2019 10-K restates 2018's "other" as 890M (the bank loans folded in).

Quarter ends are not affected: the 10-Q tags only the total, which #415 counts in place of the year-end parts.

**Who else files the tag** (each company's company facts, every period): Coca-Cola, as a part *inside* its `ShortTermBorrowings` at 2019–2022 (2019: 10,994M = commercial paper 10,007M + other 987M) and beside commercial paper with no `ShortTermBorrowings` and no `DebtCurrent` at 2023–2025 (348M, 360M, 56M); Apple, in three 10-Qs (2019-09-28 equal to its commercial paper, 5,980M; 2020-03-28 and 2020-06-27, 10,029M and 11,166M, with no commercial paper tagged); Exxon, in two 2012 10-Qs (2.7M and 2,808M). Caterpillar, Johnson & Johnson, Microsoft and Walmart never file it.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. Read P&G's "other" short-term borrowings as its short-term borrowings.**
  - New map row: `short_term_borrowings, us-gaap:OtherShortTermBorrowings, 3`, with the item's unit, period type, gate and definition (the loader requires them shared), `companies=PG` (#341's scoped row: ingest stores the tag for P&G only, and a scoped row can't be priority 1). Note: P&G's debt note lists "Other" short-term borrowings beside commercial paper and the current portion; `DebtCurrent` equals the three at every year end 2009–2016 and 2019–2026; priority 3, so at 2017 and 2018 the bank loans (priority 2) are read and "other" is not; not global (Coca-Cola, Apple below).
  - Nothing in the engine changes. With the row, a P&G year end has a `short_term_borrowings` fact dated at its balance date, and the existing rules read it:
    - #408 (`current_debt_inside`): the total is nearer the parts with the current portion than without it (2021: |8,889 − 98| = 8,791 against |8,889 − 98 − 3,620| = 5,171), so the current portion stays counted.
    - #412 (`paper_beside`): the total is the three parts exactly, nearer than without commercial paper and within half of it, so commercial paper is counted beside the "other" line, with run note `commercial_paper_beside_short_term` (params `short_term_borrowings` = the other line, `short_term_left_out` null). Before the row, from 2019 the same note fired with P&G's 2018 bank loans (800M) as an older figure left out; from 2009 to 2016 no short-term figure existed, so commercial paper counted in its place and no note fired.
    - #415 (`total_in_place`): a quarter end still has no part dated at it, so the quarter's total is counted; `parts_left_out` now lists the last year end's "other" line (item `short_term_borrowings`, reason `older`) where it listed the 2018 bank loans.
    - Debt at a P&G year end = current portion + other + commercial paper + non-current debt; the debt due within a year matches the filing's total at every year end 2009–2016 and 2019–2026.
  - The map's copy in `concept_maps/` and its `CHANGES.md` line in the same commit (`tests/fundamentals/test_concepts.py` requires them). `known_gaps.csv`: P&G's `short_term_borrowings` row narrows from every period to `Q1;Q2;Q3` ("[annual only]", as Exxon's and Caterpillar's).
  - `READING_RULES_VERSION` stays 10 and no row is added: no code changes, and which figures a run reads is pinned by the map's fingerprint (`runs.concept_map_sha256`; stored runs rebuild through their own map). Beside an older P&G run of the same date this is the brief's "same reading rules, different map fingerprints" case (#341's precedent).
  - Tests:
    - `tests/fundamentals/test_concepts.py`: the shipped map's scoped rows are CAT's maturities tag and P&G's other short-term borrowings (the existing test names both).
    - `tests/fundamentals/test_ingest.py`: through the shipped row, `extract_facts` keeps `OtherShortTermBorrowings` for PG and skips it, counted under `company_scope`, for KO, AAPL and XOM.
    - `tests/analysis/test_other_short_term.py` (new; fixture `company` from `tests/analysis/conftest.py`, `put` from `tests/analysis/test_debt_current_inside.py`; the fixture's current portion 20, non-current 180):
      - P&G's year end: other 5, commercial paper 70, total 95 at the balance date: debt 275 (20 + 5 + 70 + 180), rows `balance:short_term_borrowings` 5 citing `OtherShortTermBorrowings` and `balance:commercial_paper` 70, the #412 note with `short_term_borrowings` 5 and nothing left out, no #408 note.
      - Through the map before this change (`52635076391a`): the same facts give debt 270, commercial paper in place of short-term borrowings, no #412 note (what a stored run rebuilds to).
      - 2017/2018 (the pinned limit): bank loans 10 and other 5 at one date with paper 70 and total 105: bank loans are read (priority 2), debt 280, the 5 is not counted.
      - A quarter end with only its total, after a year end with other, paper and the current portion: the total is counted in their place and `parts_left_out` lists the other line as `short_term_borrowings`, reason `older`.
      - The reported view (`reported._net_debt`) gives the same debt due within a year at the year end as the run.
  - Exit: full suite, `ruff check .` and `ruff format --check .` clean.

- **Step 2. Real data.** On the worktree's copy of the restored snapshot (`warren-20261116T053654Z`):
  - `python -m domains.fundamentals ingest --all` from the cached company facts (no download), so no fresh run carries `concept_map_changed`: expected, only P&G gains facts (its `OtherShortTermBorrowings` values), every other company skips its own under `company_scope`. `python -m domains.fundamentals report --all`: no unexplained gap.
  - `python -m domains.analysis debt-checks --ticker PG --near-misses`: expected, only 2017-06-30 and 2018-06-30 left (the limit above), now with rule `beside`.
  - `reproduce --all --rebuild`: every stored run reproduces to the cent and rebuilds as before (each through its own map, which never read the tag).
  - Every stored run date (903 that are not what-ifs) built fresh in memory, pinned to its market downloads and choices, through the map before and after the row (a copy of the database with the facts in both cases, the old map applied with `concept_map_in_force`): expected, only P&G runs move; listed with debt, cost of debt, `nwc_pct` and value per share before and after, by year of run date.
  - Exit: only P&G moves; every moved P&G run with a year-end balance date has debt due within a year equal to the filing's total (2009–2016 and 2019–2026).

## Alternatives considered

- **The same row for every company.** Coca-Cola 2023–2025 would read its "other" line (348M at 2023-12-31) as short-term borrowings, and since Coca-Cola never tags `DebtCurrent`, #412 can't show commercial paper is beside it: commercial paper (4,209M) would stop counting, as it does only in place of short-term borrowings without the total. At 2019–2022 `ShortTermBorrowings` (priority 1) wins, so nothing changes there. Apple's 10-Q tag stands for its commercial paper (equal to it at 2019-09-28), and Exxon's two 2012 10-Q figures don't fit its total. So the row is P&G's only. Coca-Cola's own gap (its "other" line beside commercial paper since 2023: 348M, 360M and 56M) is a follow-up issue, not this track: it needs a rule without a filed total to check against.
- **Count the filing's total in place of the parts whenever they fall short by more than a rounding** (the issue's second option). It needs a tolerance with no source, and it would replace three traced lines a student can read with one at every year end, which #415 rejected for the same reason; the tag gives the missing line itself.
- **"Other" above the bank loans (priority 2 for P&G, bank loans 3).** At 2017 it would count 173M where today counts 0 (exact), but at 2018 a run dated before the FY2019 10-K would read 90M and lose the 800M bank loans, and after it read the restated 890M. Priority 3 never loses a figure Warren counts today; the 173M and 90M stay out (Limits).
- **A new map item `other_short_term_borrowings` added as a fourth part.** Needs a rule for when it is inside short-term borrowings (Coca-Cola 2019–2022) and when beside it, with no total for Coca-Cola to judge by; for P&G, the only company with a total, it would read the same figures as the scoped row.

**Limits.** P&G's 2017-06-30 and 2018-06-30 year ends keep their short-term bank loans and leave the "other" line out (173M, 90M), as today; those years are only read as history years by the earliest supported runs. The row trusts P&G's tagging to stay the same; a filing that changes it shows in `debt-checks` as a near miss.

## Files to change

`domains/fundamentals/concept_map.csv`, `concept_maps/<new sha>.csv` and `CHANGES.md`, `domains/fundamentals/known_gaps.csv`; `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, `tests/analysis/test_other_short_term.py` (new); this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8 and value per share), Q1 and Q2 through the reported view's `net_debt`, and Q4 (the cost of debt and the debt weight): a fresh P&G run counts its "other" short-term borrowings at every year end it reads, so its debt due within a year matches the 10-K's own total. Fresh P&G runs move by small amounts (Step 2 gives them); stored runs keep their rows.

- **Changed on a fresh P&G run whose balance date is a year end:** a `balance:short_term_borrowings` row (the "other" line, source tag `OtherShortTermBorrowings`) beside `balance:commercial_paper`; the `debt` row's value and method; the `commercial_paper_beside_short_term` note's params (`short_term_borrowings` is the other line, `short_term_left_out` and its date are null, where from 2019 they named the 2018 bank loans).
- **Changed on a fresh P&G quarter-end run:** the `debt_current_total_in_place` note's `parts_left_out` lists the last year end's other line as `short_term_borrowings` (reason `older`) where it listed the 2018 bank loans (800M).
- **Every fresh P&G run:** history years' working capital (`nwc_pct`) and the cost of debt read the year ends with the other line.
- **Two runs of the same date:** reading rules stay 10; the map fingerprint changes, so beside an older P&G run of the same date the brief's "same reading rules, different map fingerprints" case applies (brief line 109), as it did for Caterpillar in v0.9.77.
- No output, code, param, lesson or label added, renamed or removed. The label for `short_term_borrowings` is the one #297 item 5 and #415's Product impact already wait on.
