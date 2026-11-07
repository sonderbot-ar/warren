# Backlog #256: past events say whose filings stop, and the universe note can't name a later date

Issue: https://github.com/sonderbot-ar/warren/issues/256 · Branch `backlog-256-coverage-role` · Version v0.9.36 (planned).

## Problem

The design review of #252 part 1 (v0.9.35) left three ideas. This item takes items 1 and 3; item 2 stays open on the issue.

1. **Whose filings stop** (professor). `past_events(...).notes` carries one `beyond_history` note per company in the answer whose filings are missing by D. Exxon is in every `m_and_a` answer as a *case* company (the Pioneer deal), so a Microsoft merger question dated after 2026-08-03 carries Exxon's note. Its text ("XOM (CIK …) as of D: … recent periods will be absent") can read as being about the question. What shrinks is Exxon's case: its usual-miss set and its recent quarters, not Microsoft's.
2. **A timing clause in the merger caveat** (professor, analyst). Not taken: it only matters beside shocked forecasts, and the answer shows baseline forecasts only. Revisit with #102 and #115.
3. **A date in the universe note after the cut-off** (analyst). The coverage note shows `universe.csv`'s `note` on any D from `history_ends` on (runs since v0.9.22, past events since v0.9.35). An edit such as "the two CIKs were linked in 2027" would show a 2027 fact on a 2026-09-01 question. Nothing stops it today.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. A `role` on the past-events coverage note.** `coverage_notes(question, cases, on)` takes the question's ticker and the case tickers apart. Each `beyond_history` note gains `role`: `question` when the company is the question's (also when it is a case company too), `case` otherwise. Sorting: the question's company first, then the case companies by ticker. The eight run fields (`ticker`, `cik`, `as_of`, `history_ends`, `reason`, `successor_cik`, `successor_name`, `note`) are unchanged and `role` is added; only past-events notes carry `role` (a run's note has none: it is always about the run's own company, so a missing `role` means the question's). A `question` note's text is the run's text exactly. A `case` note's text leads with one sentence, so the rest is not read as being about the question: "XOM is in this answer as a past case, not the question's company: its filings from 2026-08-03 on are missing here, so its typical forecast errors, and any of its case quarters reported from then on, stop at that date." then a space and the run's text. The app should build its sentence from `role` and the params and keep `text` as a fallback (as for every coded note since #172). `past_events` always has a question ticker (a required argument, refused when not ingested), so the question's company is always known.
  Tests: a case company's note has `role` `case` and the added sentence; the question company's note has `role` `question` and the run's text exactly; a company that is both gets one note, `question`; the question's note comes first.
  Exit: tests pass; the other past-events tests unchanged.
- **Step 2. The loader refuses a note that names a later date.** The rule: a cut-off row's `note` states only what was public on `history_ends`, because it is shown on any D from then on. `load_universe` checks it as a backstop, on rows with `history_ends`: refused are an ISO date after the cut-off (also followed by a time, `2026-11-04T00:00`); a month and year ("November 2026") or a calendar quarter ("Q4 2026", "4Q2026") that begins after the cut-off (the month or quarter that holds the cut-off passes: "Q3 2026" on 2026-08-03); a fiscal year ("fiscal 2028", "FY2028") more than one year past the cut-off's year (Walmart's fiscal 2027 began in February 2026); any other year after the cut-off's year, except a maturity ("notes due 2030"). Each refusal names its line, like every other loader error, so the checked-in file and any file passed with `--universe` get the same guard (Decision 11: companies are data). Not checked, said in the docstring: relative phrases ("next year", "later", "now") and slashed dates; the author keeps to the rule. A row without `history_ends` is not checked: its note is never shown as a coverage note, by runs or past events.
  Tests: the checked-in file loads (Exxon's note names 2026-07-01, Q2 2026 and 2026-08-03); refused, each with its line: a later ISO date, with and without a time, a not-a-date, a later year, a later month, a later quarter in both spellings, a fiscal year two past; loading: the cut-off and earlier dates, a CIK, the quarter that holds the cut-off, fiscal 2027 on a 2026 cut-off, a maturity; a later year on a row without a cut-off.
  Exit: tests pass.
- **Step 3. Real data** (snapshot `warren-20261105T101750Z`): `past-events --json` for Q10 (MSFT `m_and_a`) and Q14 (XOM `macro`) on 2026-11-07, before (main) and after: identical apart from `role` and the added sentence on Exxon's case note in Q10; Q14's Exxon note is `question`.

**Point in time.** Nothing new is read. Step 2 is what keeps the shown note point in time on any D from the cut-off. **LLMs.** None. **Decision 11.** The check lives in the loader, so a new company row gets it with no code change.

## Alternatives considered

- **A test on the checked-in file only** (the issue's wording). Rejected: a file passed with `--universe` would skip it; the loader is where every other row rule lives.
- **Drop the coverage note for case companies.** Rejected: Exxon's case really is shorter after the cut-off, and the student should be told.
- **Put `role` on the run's note too.** Rejected: a run has one company; the field would always say `question`.
- **A year check only.** Rejected in review: "November 2026" or "Q4 2026" on a 2026-08-03 cut-off is after it but carries the cut-off's own year. Months and quarters are checked against their first day.
- **Refuse every later year, fiscal or maturity too.** Rejected: Walmart's and Microsoft's fiscal years are named after the calendar year they end in, and a bond's maturity is public at issue; both would be refused loudly for no leak.

## Files to change

`domains/evaluation/past_events.py`, `domains/fundamentals/universe.py`, `tests/evaluation/test_past_events.py`, `tests/fundamentals/test_universe.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q10–Q15 ("Eventos"). `beyond_history` notes on `past_events(...).notes` gain one param, `role` (`question` or `case`); the question's company's note now comes first. The app can say "Exxon, one of the past cases, …" instead of reusing the run's sentence as if it were about the question. No other field changes; runs' notes are unchanged. A new loader error can refuse a `universe.csv` whose note names a date after its cut-off; the checked-in file passes.

## Design review (nov.07.2026)

Explainer, analyst, professor and product lead in parallel, after Steps 0–2 were committed.

- **Professor: one blocker, taken.** The doc claimed a year check catches any later date in words; "October 2026", "Q3 2026" or "late 2026" carry the cut-off's own year. Months and calendar quarters are now checked against their first day, and the doc states the rule (a note says only what was public at the cut-off) with the check as its backstop, naming what it can't see ("next year", "later"; the checked-in note's "now maps" and "a later task" describe the repo, not later public facts). Taken: "usual misses" replaced by plain words, the cut-off date named, and the case sentence put first so the rest is not read as about the question. Idea for the front-end: the company's name rather than its ticker in the student's sentence.
- **Analyst: GO, no blockers.** Taken: the case sentence no longer says the case's quarters "end early" (the Pioneer case's quarters were all filed by 2024; what is cut is Exxon's typical-error history, and any case quarter reported after the cut-off); later months in the cut-off's year; an ISO date followed by a time; "FY2027" (no word break before the year); fiscal years and maturities were wrongly refused (now allowed within one year, and "due YYYY"); the checked-in-file test's docstring says what it asserts. Not taken: slashed dates, documented as unchecked.
- **Explainer: one blocker, rejected with a reason.** It asked how the question's company is found when a question has no ticker. `past_events` always has one: `ticker` is a required argument and an un-ingested ticker is refused (`domains/evaluation/past_events.py`, `past_events`). Gaps taken: the eight fields listed; the case sentence's template and joining stated; a missing `role` on a run's note stated; which rows are checked stated.
- **Product lead: no blockers.** Taken: the doc says a missing `role` means the question's company, `role` is `question` or `case` only, and the app should render from params with `text` as a fallback. The ordering test already has both companies with gaps. Idea, filed: whether a case whose data ends early is still counted in the "few cases" line.

