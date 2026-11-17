# Backlog #432: Coca-Cola's "Loans and notes payable", read as its short-term borrowings

Issue: https://github.com/sonderbot-ar/warren/issues/432 (found by the #426 design review, `docs/designs/backlog-426-pg-short-term-gap.md`, Alternatives) · Branch `backlog-432-ko-loans-and-notes` · Version v0.10.2, merged nov.17.2026 (PR #446, merge `0570ee8`, after CI green and a gatekeeper GO).

## Problem

Coca-Cola's balance sheet has one line for its short-term borrowing other than the current portion of long-term debt: "Loans and notes payable", which holds its commercial paper and its other short-term borrowings together. Warren doesn't read that line (`known_gaps.csv`, KO row: "bundles commercial paper ... not mapped to avoid double counting"). It reads `ShortTermBorrowings` where KO tags it and otherwise counts commercial paper in place of short-term borrowings. KO's tagging (SEC company facts, CIK 0000021344, every filing):

| Balance dates | `ShortTermBorrowings` | `CommercialPaper` | `OtherShortTermBorrowings` | The line itself |
|---|---|---|---|---|
| Year ends 2009–2016 | no | yes | no | no XBRL tag in company facts |
| 2017-12-31, 2018-09-28 to 2019-09-27 (year and quarter ends) | no | year ends only | no | `NotesAndLoansPayableCurrent` (2017-12-31 first tagged in the 10-Q of 2018-10-30) |
| Year ends 2019–2022 | yes (= the line) | yes | yes, *inside* it | `NotesAndLoansPayable` (in the next 10-Qs; the 2022 10-K too) |
| Quarter ends 2020–2022 | no | no | no | `NotesAndLoansPayable` |
| Year and quarter ends 2023 on | no | yes (from 2022-12-31 in 10-Qs) | year ends only, *beside* the paper | `NotesAndLoansPayable` |

So Warren is wrong for KO in three ways, of which the issue named only the first. A figure up to 370 days old is carried to a later balance date when none is filed there (`latest_before`, analyst), and a short-term figure, however old, is read before the paper of the balance date (fresh runs on the restored data, Step 2):

1. **Year ends 2024 and 2025: the "other" line is lost** (the issue): paper counts in place of short-term borrowings, short by 360M and 56M.
2. **2023, year and quarter ends: last year's figure is carried.** 2022-12-31's `ShortTermBorrowings` (2,373M) is read at 2023-03-31 (the line 5,455M), and at 2023-12-31 (the line 4,557M = paper 4,209M + other 348M): short by 2,184M, not the issue's 348M.
3. **Quarter ends 2019–2022: an older figure is carried.** Only the line is tagged at those dates. A run dated 2020-06-01 (balance 2020-03-27, the line 13,657M) read the 2019-12-31 paper, 10,007M; runs dated 2020-11-01 to 2021-02-01 (balance 2020-09-25, the line 5,857M) read the same 10,007M, 4,150M too much.

Coca-Cola never tags `DebtCurrent`, so none of #408's, #412's or #415's checks can tell it apart; the line itself is the total those rules look for, and it is what the balance sheet shows.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. Read Coca-Cola's "Loans and notes payable" as its short-term borrowings.**
  - Two map rows for `short_term_borrowings`, both `companies=KO` (#341's scoped rows; a scoped row can't be priority 1): `us-gaap:NotesAndLoansPayableCurrent`, priority 4, and `us-gaap:NotesAndLoansPayable`, priority 5, with the item's shared unit, period type, gate and definition. Note: KO's balance-sheet line "Loans and notes payable" holds commercial paper and other short-term borrowings and not the current portion of long-term debt (`LongTermDebtCurrent`, its own line); equal to `ShortTermBorrowings` at every year end 2019–2022 and to paper + other at 2023-12-31 (4,557M = 4,209M + 348M). Scoped to KO because the same tags may mean other things elsewhere (Exxon's "Notes and loans payable" is tagged `DebtCurrent` and includes its current portion).
  - The KO row in `known_gaps.csv` ("[bundled] ... not mapped") narrows to the years with no tag for the line (2009–2016) and is reworded: commercial paper counts in place of short-term borrowings; the small other line is left out.
  - Nothing in the engine changes. With the rows, a KO balance date from 2017-12-31 on has a `short_term_borrowings` fact dated at it, and the existing rules read it:
    - Which tag: per balance date, the highest-priority tag filed for it by the as-of date (`facts.py`). At year ends 2019–2022 `ShortTermBorrowings` (priority 1) is read, as today, with the same value.
    - Commercial paper: with a short-term figure and no `DebtCurrent`, #412 never fires, so paper is not added (`debt_parts`, `_operating_nwc`): the line already holds it. No double count.
    - #408 and #415 need `DebtCurrent`, which KO never tags: they never fire for KO, before or after.
    - The current portion (`LongTermDebtCurrent`) is still counted beside the line.
  - Map copy in `concept_maps/` and a `CHANGES.md` line (required by `tests/fundamentals/test_concepts.py`).
  - `READING_RULES_VERSION` stays 10 and no row is added to `reading_rules.md`: no code changes; the map fingerprint pins which figures a run reads (stored runs rebuild through their own map), as in #426.
  - Tests:
    - `tests/fundamentals/test_concepts.py`: the shipped map's scoped rows now name KO's two tags beside CAT's and P&G's.
    - `tests/fundamentals/test_ingest.py`: through the shipped rows, `extract_facts` keeps both tags for KO and skips them, counted under `company_scope`, for another company.
    - `tests/analysis/test_loans_and_notes.py` (new; the fixture and helpers of `test_other_short_term.py`):
      - 2023 year end: paper 70 and the line 75 (`NotesAndLoansPayable`) at the balance date: debt = current 20 + non-current 180 + 75 = 275, the `balance:short_term_borrowings` row is 75 citing `NotesAndLoansPayable`, paper not counted, no #412 note.
      - Through the map before this change: the same facts give 270, paper in place (what a stored run rebuilds to).
      - A quarter end with only the line, after a year end with a `ShortTermBorrowings` figure: the quarter's line is read, not the year end's.
      - A year end with `ShortTermBorrowings` and the line both: `ShortTermBorrowings` is read (priority 1).
      - Point in time: a line filed after the as-of date is not read; paper is counted in place, as today.
      - The reported view's `net_debt` at the same date gives the same debt due within a year as the run.
  - Exit: full suite, `ruff check .` and `ruff format --check .` clean.

- **Step 2. Real data.** On a copy of the restored snapshot:
  - `fundamentals ingest --all` from the cached company facts: only KO gains facts. `fundamentals report --all`: no unexplained gap.
  - `reproduce --all --rebuild`: every stored run reproduces to the cent and rebuilds as before.
  - Every stored run date built fresh in memory through the map before and after (pinned market data and choices, as in #426): expected, only KO runs move; listed by year with debt, cost of debt, `nwc_pct` and value per share before and after.
  - Exit: only KO moves; every KO run whose balance date is 2017-12-31 or later reads the line of its own balance date (or `ShortTermBorrowings` of equal value).

## Results (Step 2, nov.17.2026)

On a copy of the restored snapshot (`warren-20261117T051108Z`).

- **Ingest.** `fundamentals ingest --all` from the cached company facts: KO gains 60 facts (both tags, every filing's version); every other company gains none. `fundamentals report --all`: 0 unexplained gaps for all eight companies.
- **Stored runs.** `reproduce --all --rebuild`: 903 of 903 reproduced to the cent; 692 of 903 rebuilt to identical rows, the same count as before (each through its own map).
- **Fresh runs.** Every stored run date built twice in memory (pinned market data and choices) through #426's map and today's: none refused; no run of the other seven companies changes a row or a note. 110 of 114 KO runs move (the four that don't are dated 2022-03-01 to 2023-04-01 with a 2022-12-31 balance date, where `ShortTermBorrowings` equals the line). Every KO run with a balance date from 2018-09-28 on now reads the line of its own balance date, or `ShortTermBorrowings` of the same value.
  - The note `balance_carried_forward` changes on 42 runs: the short-term line leaves its list on 16 and its params change on 26.
  - Value per share is lower on 65 runs and higher on 45. The biggest moves: runs dated 2020-11-01 to 2021-02-01 (balance 2020-09-25) drop 4.15bn of debt (57.02bn → 52.87bn: the paper of 2019-12-31, 10,007M, was carried where the line is 5,857M), value per share up about 3.2% (2021-01-01: $22.62 → $23.38). The 2023-12-31 balance date (runs dated 2024-03-01 to 2024-04-01) gains 2.18bn (39.88bn → 42.06bn), value per share −0.8% (2024-03-01: $37.70 → $37.39).
  - History years read the line too: working capital (`nwc_pct`) moves up 0 to 1.9 points of revenue (mostly 2018's 13,835M in place of the paper's 13,063M), and the cost of debt down 0 to 4.5 basis points (professor: the line is seasonal, but the cost of debt reads year ends, so the swing doesn't reach it).

| Runs dated | Runs moved | Debt | Cost of debt | `nwc_pct` (first quarter) | Value per share |
|---|---|---|---|---|---|
| 2019 | 12 of 12 | −2,091M to +131M | −2.3 to −0.9 bp | +40 to +107 bp | −0.05% to +1.76% |
| 2020 | 14 of 14 | −4,150M to +3,650M | −4.5 to −2.3 bp | +107 to +189 bp | −1.54% to +3.16% |
| 2021 | 15 of 15 | −4,150M to 0 | −4.5 to 0 bp | +75 to +189 bp | +0.02% to +3.35% |
| 2022 | 13 of 15 | −317M to +1,051M | 0 | 0 to +75 bp | −0.54% to +0.28% |
| 2023 | 12 of 14 | 0 to +3,082M | 0 | 0 | −1.13% to 0.00% |
| 2024 | 14 of 14 | +291M to +2,184M | −1.6 to 0 bp | 0 to +25 bp | −0.87% to −0.09% |
| 2025 | 14 of 14 | +327M to +386M | −3.2 to −1.6 bp | +25 to +51 bp | −0.16% to −0.11% |
| 2026 | 16 of 16 | −202M to +327M | −3.2 to −1.7 bp | +51 to +55 bp | −0.12% to +0.09% |

Revenue and EBIT forecasts don't read debt, so forecast-error scores don't move.

## Alternatives considered

- **The issue's first idea: read `OtherShortTermBorrowings` for KO and add commercial paper beside it, checked against `NotesAndLoansPayable` as a check-only total.** It fixes only year ends 2023–2025 (the other line is tagged only at year ends), needs a new check path in #412's rule, and leaves problems 2 and 3 (quarter ends) as they are. Reading the line itself fixes all three with map rows only.
- **Map the line for every company.** Not known to mean the same thing elsewhere; companies as data (Decision 11) favours a scoped row until another company is checked.
- **Keep the parts (paper and other) as separate rows for the student.** The line is what the balance sheet shows, and the parts are tagged only at year ends; at quarter ends there are no parts to show.

**Limits.** Year ends 2009–2016 (history years only) still leave the other line out, so a student comparing years sees a small step at 2017. Those years have no `us-gaap` tag for the line (KO used its own `ko:LoansAndNotesPayable`, which ingest doesn't read: #445), so commercial paper still counts in place of short-term borrowings and the other line (small: e.g. the line 12,498M against paper 12,330M at 2016-12-31, from the 10-K's balance sheet) is left out; these years are read only as history years by the earliest supported runs. Quarter ends before 2018-09-28 have no paper and no line, so the last year end is carried forward, as today. Runs dated 2018-02-23 to 2018-10-29 read 2017-12-31's paper (12,931M), not the line (13,205M), because the line was first tagged in the 10-Q of 2018-10-30. The 8-K of 2019-09-20 recast 2017 and 2018 for CCBA (back from "held for sale"); 8-Ks are not ingested, so history year 2017 stays on the old basis (13,205M) while 2018 is read on the new one (13,835M from the 10-Q of 2019-07-25). The rows trust KO's tagging to stay as it is.

## Files to change

`domains/fundamentals/concept_map.csv`, `concept_maps/<new sha>.csv` and `CHANGES.md`, `domains/fundamentals/known_gaps.csv`; `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, `tests/analysis/test_loans_and_notes.py` (new); this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8 and value per share), Q9 (Coca-Cola's sensitivity grid: the run's own point moves) and Q7 (it starts from a run), the reported view's `net_debt` (Q1 and Q2; Q2's operating margin doesn't change), and Q4 (the cost of debt and the debt weight): a fresh Coca-Cola run reads the short-term borrowing its balance sheet shows at its own balance date. 110 of 114 fresh KO runs move (Results); stored runs keep their rows.

- **Changed on fresh KO runs:** the `balance:short_term_borrowings` row appears where only `balance:commercial_paper` was (year and quarter ends from 2022-12-31, and 2017-12-31 and 2018-12-31 once tagged), its source tag `NotesAndLoansPayable` or `NotesAndLoansPayableCurrent`; at quarter ends 2019–2022 it is the quarter's own figure instead of an older one. The `debt` row's value and method; history years' working capital and the cost of debt. `balance_carried_forward` (brief lines 159, 161) changes on 42 runs: the short-term line leaves its list on 16 and its params change on 26; "papel comercial" leaves the KO table where the line is read.
- **Label:** the line's own name in the filing is "Loans and notes payable" ("Préstamos y documentos por pagar"); the item's current label ("préstamos bancarios de corto plazo", brief line 159) is too narrow for it and waits on #297 item 5, as in #426. Until then, a *Fuente* sentence keyed on the source tag (`NotesAndLoansPayable` or `NotesAndLoansPayableCurrent`), as for Exxon's finance leases (line 171): "Es la línea 'Préstamos y documentos por pagar' del reporte; incluye el papel comercial." No series note for Q2's net debt: the step at 2017 (before, paper only; after, the whole line) is small. The line holds commercial paper, so the app should not show a separate commercial paper row beside it for KO (the engine doesn't emit one where the line is read).
- **Two runs of the same date:** reading rules stay 10, the map fingerprint changes. All 114 stored KO runs have no recorded reading rules, so beside any of them the brief's "either NULL" case applies (line 108: add KO to its list); beside a later fresh KO run stored under rules 10, the "same reading rules, different map fingerprints" case (line 109): the fresh value is lower on 65 of 114 dates and higher on 45 (e.g. 2021-01-01 $22.62 → $23.38; 2024-03-01 $37.70 → $37.39).
- No output, code, param, lesson or label added, renamed or removed.

## Design review (nov.17.2026)

- **Analyst, GO once one blocker is fixed (taken).** Confirmed against the filings: the line and "Current maturities of long-term debt" are separate balance-sheet lines (2016 10-K, R4: 12,498M and 3,527M), so no double count; `ShortTermBorrowings` equals the line at every year end 2019–2022 (10,994M, 2,183M, 3,307M, 2,373M); 4,557M = 4,209M + 348M at 2023-12-31 and 2,373M = 2,146M + 227M at 2022-12-31; 2018-12-31's 13,194M → 13,835M from the 10-Q of 2019-07-25 is CCBA's borrowings coming back from "held for sale" (8-K of 2019-09-20), which the newest-version rule picks up by as-of date; 12,498M against paper 12,330M at 2016-12-31 confirmed; before 2017-12-31 the line is tagged only under KO's own tag `ko:LoansAndNotesPayable`, which ingest doesn't read. **Blocker taken:** the Problem misstated today's numbers, because a figure up to 370 days old is carried (`latest_before`): at 2023-12-31 the run read 2022-12-31's `ShortTermBorrowings` (2,373M), not the paper, so it was short by 2,184M, not 348M; and a 2020-03-27 run read the 2019-12-31 paper (10,007M). Problem rewritten from the fresh runs (Step 2). Ideas taken: a year-end test with last year's figure carried (`test_a_year_end_reads_its_line_not_last_years_borrowings`); the 2018 window and the CCBA basis in Limits; the 2023-12-31 move named in Step 2. Filed as #445: reading `ko:LoansAndNotesPayable` for 2009–2017 (needs custom-tag ingest).
- **Professor, accept, no blockers.** Koller, Goedhart and Wessels and Damodaran count all interest-bearing short-term borrowing as debt; reading the face statement's line is the faithful reading (S-X 5-02.19, cited from memory: the rule's site was not reachable from the session). Taken: Step 2 reports how much KO's cost of debt moves, since the line is seasonal; Limits says 2009–2016 history years leave the other line out. Ideas for the lesson: the 2023 bridge (paper + other = the line, plus the current portion) as a worked example; a note that KO's short-term debt swings between quarters because commercial paper is seasonal.
- **Explainer.** Gaps taken: the stale note on the bank-loans row (it said the tag was "deliberately not mapped"), the before-map fingerprint (#426's, `86f87e48e967`, named in the tests), the 2017-12-31 point-in-time case, the reported view (it reads debt through the same `debt_parts`). Not taken: the working tree ran ahead of the doc while the review ran (Step 1 was being built); the doc is the plan.
- **Product lead, four blockers, all taken** (Product impact): Q9 (Coca-Cola's sensitivity grid) and Q7 start from a run, so they move too; the two-runs case is "either NULL" for most stored KO runs (rules not recorded before v0.9.67), so the counts are given; `balance_carried_forward` changes on quarter-end runs; a *Fuente* sentence keyed on the source tag until #297 item 5 sets the label.

## PR review (nov.17.2026)

- **Gatekeeper, NO-GO, one blocker (taken):** the working-capital test passed over an empty list, because the line was put only at the balance date, never at a history year end. Now the line and the paper sit at a history year end and the test checks that year's working capital moves by exactly the line less the paper. Taken: the known-gaps KO row links #445; this doc's status. Ideas for backlog: pin the fresh-run counts in a small fixture-level regression; a guard against `all(...)` over an empty list in tests.

## Where the work stopped

Done: merged as v0.10.2. The gatekeeper's second look gave GO (2c51908).
