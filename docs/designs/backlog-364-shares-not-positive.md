# Backlog #364: a share count of zero or below is never used

Issue: https://github.com/sonderbot-ar/warren/issues/364 · Branch `backlog-364-shares-not-positive` · Version v0.9.68 (planned)

## Problem

Coca-Cola's 10-Q/A, accession 0001047469-09-009321, files its cover-page shares outstanding (`dei:EntityCommonStockSharesOutstanding`) as 0.0 for 2009-10-23. Warren stores facts as filed (Decision 2), so the zero is in the database.

What `domains/analysis/math_engine.py` `_shares` does with a count like that today:

1. **A newest cover count of zero is divided by.** `_shares` takes the newest cover count as the run's shares. If that count were zero, the market value would be zero and the value per share would divide by zero.
2. **A newest diluted count of zero crashes the check.** Beside a cover count, `_shares` compares it with the newest diluted count (`shares / diluted_now - 1`). A diluted count of zero raises `ZeroDivisionError`, which is not an `EngineError`, so the run fails with a stack trace instead of a reason.
3. **The fallback would use it.** With no cover count, the newest diluted count is used; `share_scale` (#343) returns `None` for zero, so a zero is not caught as a unit error.

No stored run and no run possible today reads the 2009 zero: runs start at 2019-03-01 (`SUPPORTED_FROM`), and every KO run's newest cover count is a later, positive one. The fix matters if the supported range moves back, or another company files a zero.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. Skip counts not above zero, and say so.** In `_shares`, cover and diluted counts are each filtered to those above zero before anything is chosen or compared (`positive(...)` inside `_shares`):
  - A count of zero or below that is **newer than the newest count above zero** (so it would have been the one used or compared) gives run note `shares_not_positive`, params `count` (`cover` or `diluted`), `value` (as filed), `accession_no` and `period_end` (ISO), so the app can link the filing, and `divisor` (true when the skipped count would have been the run's share count; false for a diluted count that only fed the check beside a cover count, so the app can say the value did not move). English: "Cover-page shares for 2020-04-20 are filed as 0 (0000000123-20-000016); a share count must be above zero, so that count is not used".
  - With **no count above zero** of that kind, only the newest is noted (one note, not one per filing), and `_shares` falls back as before (cover → diluted).
  - An **older** count of zero or below is left out silently: it would never have been used, and noting it would put Coca-Cola's 2009 filing on every KO run. It only leaves the fallback's middle count (#343), where a zero has no meaning anyway.
  - With no count above zero at all, `EngineError("<ticker>: no share count above zero reported")` (the old message stays when nothing was filed).
  - The code joins `RUN_NOTE_CODES` (`domains/analysis/coded.py`) and gets a lesson in `text.WARNING_LESSONS` (group `data`, no params, no textbook reference: it is a Warren rule, `math_engine._shares`).
  - Reading rules: this can change what a run reads, so `READING_RULES_VERSION` goes to 2, with its row in `domains/analysis/reading_rules.md`.
  - Tests (`tests/analysis/test_shares_not_positive.py`): newest cover at 0 and at −1 gives way to the cover before it (set to 95 so the test can tell), one note with its params and text; an older cover at 0 changes nothing and is not noted; every cover at 0 uses the diluted fallback and notes only the newest cover; a newest diluted count of 0 beside the cover no longer divides by zero, gives one note and no `shares_cover_differs`; the fallback skips a diluted count of −100; nothing above zero is refused with `EngineError`; positive counts change nothing.
  - Exit: tests pass; ruff clean.
- **Step 2. Real data.** On the snapshot (nov.10): list every share-count fact of zero or below; rebuild every stored run on `main` and on this branch and compare; check no KO run gains the note. Exit: the results written here, `reproduce --all` 903 of 903.

## Real data (Step 2, nov.14.2026)

_Filled in below when the checks finish._

## Alternatives considered

- **Raise `EngineError` on any count of zero or below** (the issue's second option). Rejected: an earlier filed count above zero is a real number, usually a quarter older, and #343 already set the pattern of skipping a bad count with a note rather than refusing the run.
- **Drop the fact at ingest.** Rejected: facts are stored as filed (Decision 2); changing what is stored is an amendment the owner approves (#280, #322). The engine never needs the zero, so the fix stays in the engine.
- **Note every count of zero or below in the history.** Rejected: a 2009 filing error would appear on every Coca-Cola run though it changes nothing they read.

## Known limits

- A count that is positive but absurdly small (a blank saved as 1, say) is not caught here; #343 catches it only when it is a power of a thousand off, and #368 item 1 covers how a tiny count prints.
- The fundamentals data-quality report does not list share counts of zero; that belongs with #368 item 2 (the SEC's hundredfold check in the report).

**Point in time.** Nothing new is read: the check uses the counts the run already loads as of its date. **LLMs.** None. **Decision 11.** No source, company or currency change. **Stored runs.** Notes are stored with each run and not changed; values never change, so `reproduce` and `rebuild` hold.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.py` and `.md`, a new `tests/analysis/test_shares_not_positive.py`, this doc; at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Brief: the run warnings the app shows (the "Datos" group, v0.9.60) and every question that shows a value per share (Q1–Q5); no answer changes today. Added: run-note code `shares_not_positive` (group `data`; params `count` (`cover` or `diluted`), `value`, `accession_no`, `period_end`, `divisor`) and its lesson (no params). The count used and its filing stay in the `shares` assumption's source. A run can carry more than one (one per newer count skipped, cover and diluted apart). Changed: a run whose shares are all zero or below is refused with "no share count above zero reported" instead of a crash. Nothing renamed or removed. Runs record reading rules v2 from now on. Effect on the front-end team: add the code and its lesson to the Spanish catalogue (#344).

## Design review (nov.14.2026)

Built with its tests before review (Step 1), as on #343. Professor and product lead in parallel; real data checked by the Elephant at Step 2.

- **Professor: GO, no blockers.** Skipping a count that can't be real and keeping cover first, diluted as fallback, matches Damodaran (*Investment Valuation*, 3rd ed.) and Koller, Goedhart and Wessels (*Valuation*, 7th ed.); noting only counts newer than the one used judged right. Suggestions **taken**: the lesson no longer says "the newest earlier count" (with every cover count at zero the run divides by a diluted count), and drops "usually a blank field saved as zero" (no source for how often); the fallback test is renamed "not above zero" to match its −100; "at most a quarter older" is now "usually". Idea for the app (show the skipped and used dates together) left to the front-end team.
- **Product lead: GO, no blockers.** Suggestions **taken**: the same lesson wording (the source of the `shares` assumption names the count used); a param `divisor`, so the app can say the value did not move when the skipped count was only a diluted count beside the cover. The note on grouping several notes per `count` goes to the brief through #344. **Filed** as #376: engine refusals as codes, since "no share count above zero reported" is English only.
