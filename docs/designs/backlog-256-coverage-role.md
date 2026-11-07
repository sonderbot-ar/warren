# Backlog #256: past events say whose filings stop, and the universe note can't name a later date

Issue: https://github.com/sonderbot-ar/warren/issues/256 · Branch `backlog-256-coverage-role` · Version v0.9.36 (planned).

## Problem

The design review of #252 part 1 (v0.9.35) left three ideas. This item takes items 1 and 3; item 2 stays open on the issue.

1. **Whose filings stop** (professor). `past_events(...).notes` carries one `beyond_history` note per company in the answer whose filings are missing by D. Exxon is in every `m_and_a` answer as a *case* company (the Pioneer deal), so a Microsoft merger question dated after 2026-08-03 carries Exxon's note. Its text ("XOM (CIK …) as of D: … recent periods will be absent") can read as being about the question. What shrinks is Exxon's case: its usual-miss set and its recent quarters, not Microsoft's.
2. **A timing clause in the merger caveat** (professor, analyst). Not taken: it only matters beside shocked forecasts, and the answer shows baseline forecasts only. Revisit with #102 and #115.
3. **A date in the universe note after the cut-off** (analyst). The coverage note shows `universe.csv`'s `note` on any D from `history_ends` on (runs since v0.9.22, past events since v0.9.35). An edit such as "the two CIKs were linked in 2027" would show a 2027 fact on a 2026-09-01 question. Nothing stops it today.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. A `role` on the past-events coverage note.** `coverage_notes(question, cases, on)` takes the question's ticker and the case tickers apart. Each `beyond_history` note gains `role`: `question` when the company is the question's (also when it is a case company too), `case` otherwise. Sorting: the question's company first, then the case companies by ticker. The run's text stays the note's first part, so the run's sentence still fits; a `case` note adds one sentence: "XOM is in this answer as a past case, not the question's company: its recent quarters and its usual misses end early." The eight run fields are unchanged; only past events gain `role` (a run's note has no role: it is always about the run's own company).
  Tests: a case company's note has `role` `case` and the added sentence; the question company's note has `role` `question` and the run's text exactly; a company that is both gets one note, `question`; the question's note comes first.
  Exit: tests pass; the other past-events tests unchanged.
- **Step 2. The loader refuses a note that names a later date.** `load_universe` checks, on a row with `history_ends`, every ISO date (`YYYY-MM-DD`) in `note` is on or before `history_ends` and every year (`19xx`, `20xx`) is on or before its year. A note naming a later date is refused with its line, like every other loader error, so the checked-in file and any file passed with `--universe` get the same guard (Decision 11: companies are data). A row without `history_ends` is not checked: its note is never shown as a coverage note.
  Tests: the checked-in file loads (Exxon's note names 2026-07-01, 2026 and 2026-08-03, all allowed); a later ISO date and a later year are each refused with the line; the cut-off date itself and an earlier year pass; a later year on a row without a cut-off loads.
  Exit: tests pass.
- **Step 3. Real data** (snapshot `warren-20261105T101750Z`): `past-events --json` for Q10 (MSFT `m_and_a`) and Q14 (XOM `macro`) on 2026-11-07, before (main) and after: identical apart from `role` and the added sentence on Exxon's case note in Q10; Q14's Exxon note is `question`.

**Point in time.** Nothing new is read. Step 2 is what keeps the shown note point in time on any D from the cut-off. **LLMs.** None. **Decision 11.** The check lives in the loader, so a new company row gets it with no code change.

## Alternatives considered

- **A test on the checked-in file only** (the issue's wording). Rejected: a file passed with `--universe` would skip it; the loader is where every other row rule lives.
- **Drop the coverage note for case companies.** Rejected: Exxon's case really is shorter after the cut-off, and the student should be told.
- **Put `role` on the run's note too.** Rejected: a run has one company; the field would always say `question`.
- **Parse month names ("August 2027").** Not needed: any such phrase carries a year, which the year check catches.

## Files to change

`domains/evaluation/past_events.py`, `domains/fundamentals/universe.py`, `tests/evaluation/test_past_events.py`, `tests/fundamentals/test_universe.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q10–Q15 ("Eventos"). `beyond_history` notes on `past_events(...).notes` gain one param, `role` (`question` or `case`); the question's company's note now comes first. The app can say "Exxon, one of the past cases, …" instead of reusing the run's sentence as if it were about the question. No other field changes; runs' notes are unchanged. A new loader error can refuse a `universe.csv` whose note names a date after its cut-off; the checked-in file passes.
