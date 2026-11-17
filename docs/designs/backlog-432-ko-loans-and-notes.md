# Backlog #432: Coca-Cola's "Loans and notes payable", read as its short-term borrowings

Issue: https://github.com/sonderbot-ar/warren/issues/432 (found by the #426 design review, `docs/designs/backlog-426-pg-short-term-gap.md`, Alternatives) · Branch `backlog-432-ko-loans-and-notes` · Status: in progress (nov.17.2026).

## Problem

Coca-Cola's balance sheet has one line for its short-term borrowing other than the current portion of long-term debt: "Loans and notes payable", which holds its commercial paper and its other short-term borrowings together. Warren doesn't read that line (`known_gaps.csv`, KO row: "bundles commercial paper ... not mapped to avoid double counting"). It reads `ShortTermBorrowings` where KO tags it and otherwise counts commercial paper in place of short-term borrowings. KO's tagging (SEC company facts, CIK 0000021344, every filing):

| Balance dates | `ShortTermBorrowings` | `CommercialPaper` | `OtherShortTermBorrowings` | The line itself |
|---|---|---|---|---|
| Year ends 2009–2016 | no | yes | no | no XBRL tag in company facts |
| 2017-12-31, 2018-09-28 to 2019-09-27 (year and quarter ends) | no | year ends only | no | `NotesAndLoansPayableCurrent` (2017-12-31 first tagged in the 10-Q of 2018-10-30) |
| Year ends 2019–2022 | yes (= the line) | yes | yes, *inside* it | `NotesAndLoansPayable` (in the next 10-Qs; the 2022 10-K too) |
| Quarter ends 2020–2022 | no | no | no | `NotesAndLoansPayable` |
| Year and quarter ends 2023 on | no | yes (from 2022-12-31 in 10-Qs) | year ends only, *beside* the paper | `NotesAndLoansPayable` |

So Warren is wrong for KO in three ways, of which the issue named only the first:

1. **Year ends 2023–2025: the "other" line is lost** (the issue): paper counts in place of short-term borrowings, so the debt due within a year is short by 348M, 360M and 56M (line 4,557M = paper 4,209M + other 348M at 2023-12-31).
2. **Quarter ends 2023 on: the same, and worse.** At 2023-03-31 the line is 5,455M and the paper 5,282M. And where the newest short-term figure is a year-end `ShortTermBorrowings` carried forward (within a year), the quarter's own paper is not counted at all: a run whose balance date is 2023-03-31 reads 2022-12-31's 2,373M instead of the quarter's 5,455M. (To be confirmed in Step 2 on the restored data.)
3. **Quarter ends 2019–2022: a year-end figure carried forward.** No paper and no `ShortTermBorrowings` are tagged at those dates, only the line, so every KO quarter-end run reads the last year end's figure: at 2020-03-27 the line is 13,657M, the carried figure 10,994M; at 2020-09-25 5,857M against 10,994M.

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

## Alternatives considered

- **The issue's first idea: read `OtherShortTermBorrowings` for KO and add commercial paper beside it, checked against `NotesAndLoansPayable` as a check-only total.** It fixes only year ends 2023–2025 (the other line is tagged only at year ends), needs a new check path in #412's rule, and leaves problems 2 and 3 (quarter ends) as they are. Reading the line itself fixes all three with map rows only.
- **Map the line for every company.** Not known to mean the same thing elsewhere; companies as data (Decision 11) favours a scoped row until another company is checked.
- **Keep the parts (paper and other) as separate rows for the student.** The line is what the balance sheet shows, and the parts are tagged only at year ends; at quarter ends there are no parts to show.

**Limits.** Year ends 2009–2016 have no tag for the line in company facts, so commercial paper still counts in place of short-term borrowings and the other line (small: e.g. the line 12,498M against paper 12,330M at 2016-12-31, from the 10-K's balance sheet) is left out; these years are read only as history years by the earliest supported runs. Quarter ends before 2018-09-28 have no paper and no line, so the last year end is carried forward, as today. The rows trust KO's tagging to stay as it is.

## Files to change

`domains/fundamentals/concept_map.csv`, `concept_maps/<new sha>.csv` and `CHANGES.md`, `domains/fundamentals/known_gaps.csv`; `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, `tests/analysis/test_loans_and_notes.py` (new); this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8 and value per share), the reported view's `net_debt`, and Q4 (the cost of debt and the debt weight): a fresh Coca-Cola run reads the short-term borrowing its balance sheet shows at its own balance date. Fresh KO runs move (Step 2 gives by how much); stored runs keep their rows.

- **Changed on fresh KO runs:** the `balance:short_term_borrowings` row appears where only `balance:commercial_paper` was (year and quarter ends from 2022-12-31, and 2017-12-31 and 2018-12-31 once tagged), its source tag `NotesAndLoansPayable` or `NotesAndLoansPayableCurrent`; at quarter ends 2019–2022 it is the quarter's own figure instead of the year end's. The `debt` row's value and method; history years' working capital and the cost of debt.
- **Label:** the line's own name in the filing is "Loans and notes payable" ("Préstamos y documentos por pagar"); the item's current label waits on #297 item 5, as in #426. The line holds commercial paper, so the app should not show a separate commercial paper row beside it for KO (the engine doesn't emit one where the line is read).
- **Two runs of the same date:** reading rules stay 10, the map fingerprint changes: beside an older KO run of the same date stored under rules 10, the brief's "same reading rules, different map fingerprints" case.
- No output, code, param, lesson or label added, renamed or removed.

## Where the work stopped

(Updated as the track moves.) Step 0 written; design review next.
